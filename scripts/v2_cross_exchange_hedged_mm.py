import asyncio
import os
import re
from decimal import Decimal
from typing import Any, Dict, List, Set, Tuple

import pyarrow.compute as pc
import pyarrow.parquet as pq
from pydantic import field_validator

from hummingbot.connector.connector_base import ConnectorBase
from hummingbot.core.data_type.common import MarketDict
from hummingbot.data_feed.candles_feed.data_types import CandlesConfig
from hummingbot.strategy.strategy_v2_base import StrategyV2Base, StrategyV2ConfigBase
from hummingbot.strategy_v2.models.executor_actions import CreateExecutorAction, StopExecutorAction

PARQUET_COLUMNS = ["timestamp", "trading_pair", "rate", "volume", "quoteVolume", "bestBid", "bestAsk", "mark_price", "openInterest", "next_funding_utc_timestamp"]
ONE_HOUR = 60 * 60
MIN_VOLUME = Decimal("1000000")
USD_QUOTE_CONNECTORS = {"hyperliquid_perpetual"}


class V2CrossExchangeHedgedMMConfig(StrategyV2ConfigBase):
    script_file_name: str = os.path.basename(__file__)
    markets: Dict[str, Set[str]] = {}
    candles_config: List[CandlesConfig] = []
    controllers_config: List[str] = []

    connectors: List[str] = ["hyperliquid_perpetual", "binance_perpetual"]
    connectors_quotes: Dict[str, str] = {
        "hyperliquid_perpetual": "USD",
        "bybit_perpetual": "USDT",
    }

    # Funding scan
    funding_data_dir: str = ""
    min_funding_rate_profitability: Decimal = Decimal("0.0005")
    funding_profitability_interval: int = 60 * 60 * 24

    # Execution parameters
    max_entry_spread_pct: Decimal = Decimal("0.002")
    slice_amount_quote: Decimal = Decimal("100")
    total_slices: int = 5
    maker_limit_offset_pct: Decimal = Decimal("0.0005")
    leverage: int = 20

    @field_validator("controllers_config", mode="before")
    @classmethod
    def _force_empty_controllers_config(cls, v):
        return []

    @field_validator("connectors", mode="before")
    @classmethod
    def _split_connectors(cls, v):
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v


class V2CrossExchangeHedgedMM(StrategyV2Base):
    _last_status_log: float = 0
    _spawned_tokens: Set[str] = set()
    _last_scan_ts: float = 0
    scan_interval: int = 60

    def __init__(self, connectors: Dict[str, ConnectorBase], config: V2CrossExchangeHedgedMMConfig):
        super().__init__(connectors, config)
        self.config = config
        self.connectors = connectors

    @staticmethod
    def _normalize_path(path: str) -> str:
        path_str = str(path or "").strip().strip('"').strip("'")
        path_str = os.path.expanduser(os.path.expandvars(path_str))
        if os.name == 'posix' and re.match(r'^[a-zA-Z]:[\\/]', path_str):
            drive = path_str[0].lower()
            rest = path_str[2:].replace('\\', '/').lstrip('/')
            return f"/mnt/{drive}/{rest}"
        return path_str

    @staticmethod
    def _split_pair(pair_str: str) -> Tuple[str, str]:
        upper_pair = pair_str.upper()
        if '-' in upper_pair:
            return upper_pair.split('-', 1)
        if '/' in upper_pair:
            return upper_pair.split('/', 1)
        return upper_pair, ''

    @staticmethod
    def _exchange_for_connector(connector: str) -> str:
        return connector.lower().split('_')[0]

    def _get_connector_quote_currency(self, connector: str) -> str:
        return self.config.connectors_quotes.get(connector, "USD" if connector in USD_QUOTE_CONNECTORS else "USDT")

    @staticmethod
    def _load_latest_rates_map(parquet_path: str) -> Tuple[Dict[str, Dict[str, Any]], Set[str]]:
        pair_info_map: Dict[str, Dict[str, Any]] = {}
        all_pairs_set: Set[str] = set()
        try:
            table = pq.read_table(parquet_path, columns=PARQUET_COLUMNS)
            tp_upper = pc.utf8_upper(table["trading_pair"])
            table = table.set_column(table.schema.get_field_index("trading_pair"), "trading_pair", tp_upper)
            dataframe = table.to_pandas()
        except Exception:
            return pair_info_map, all_pairs_set
        if dataframe.empty:
            return pair_info_map, all_pairs_set
        all_pairs_set = set(dataframe["trading_pair"].unique().tolist())
        dataframe = dataframe.sort_values("timestamp")
        latest_per_pair_df = dataframe.groupby("trading_pair", as_index=False).tail(1)

        def compute_rate_per_second(row):
            return Decimal(str(row["rate"])) / ONE_HOUR

        latest_per_pair_df["funding_rate_per_sec"] = latest_per_pair_df.apply(compute_rate_per_second, axis=1)

        for index, row in latest_per_pair_df.iterrows():
            trading_pair = str(row["trading_pair"]).upper()
            volume = Decimal(str(row.get("volume", "0")))
            if volume <= MIN_VOLUME:
                continue
            pair_info_map[trading_pair] = {
                "funding_rate_per_sec": latest_per_pair_df.at[index, "funding_rate_per_sec"],
                "mark_price": Decimal(str(row.get("mark_price", "0"))),
            }
        return pair_info_map, all_pairs_set

    def _latest_parquet_file(self, funding_dir: str, exchange: str) -> str:
        try:
            exchange_base_path = os.path.join(self._normalize_path(funding_dir), "parquet", exchange)
            if not os.path.isdir(exchange_base_path):
                return ""
            date_folders = [d for d in os.listdir(exchange_base_path) if os.path.isdir(os.path.join(exchange_base_path, d))]
            if not date_folders:
                return ""
            latest_date_dir = os.path.join(exchange_base_path, sorted(date_folders)[-1])
            parquet_files = [f for f in os.listdir(latest_date_dir) if f.lower().endswith('.parquet')]
            return os.path.join(latest_date_dir, sorted(parquet_files)[-1]) if parquet_files else ""
        except Exception:
            return ""

    def _scan_opportunities(self) -> List[Dict[str, Any]]:
        strategy_config = self.config
        available_connectors = [name for name in (strategy_config.connectors or []) if name in (self.market_data_provider.connectors or {}).keys()]
        if len(available_connectors) < 2 or not strategy_config.funding_data_dir:
            return []

        connector_to_pair_info_map: Dict[str, Dict[str, Dict[str, Any]]] = {}
        connector_to_pairs_set: Dict[str, Set[str]] = {}
        for connector_name in available_connectors:
            exchange_name = self._exchange_for_connector(connector_name)
            latest_parquet_path = self._latest_parquet_file(strategy_config.funding_data_dir, exchange_name)
            if not latest_parquet_path:
                continue

            pair_info_map, pairs_set = self._load_latest_rates_map(latest_parquet_path)
            if pair_info_map:
                connector_to_pair_info_map[connector_name] = pair_info_map
                connector_to_pairs_set[connector_name] = pairs_set

        if len(connector_to_pair_info_map) < 2:
            return []

        bases_by_connector: Dict[str, Set[str]] = {}
        for connector_name, pairs_set in connector_to_pairs_set.items():
            quote_asset = self._get_connector_quote_currency(connector_name)
            base_assets: Set[str] = set()
            for trading_pair_str in pairs_set:
                base_asset, quote = self._split_pair(trading_pair_str)
                if quote == quote_asset:
                    base_assets.add(base_asset)
            bases_by_connector[connector_name] = base_assets
        token_presence_counts: Dict[str, int] = {}
        for base_assets in bases_by_connector.values():
            for base_asset in base_assets:
                token_presence_counts[base_asset] = token_presence_counts.get(base_asset, 0) + 1
        eligible_tokens = [token for token, count in token_presence_counts.items() if count >= 2]
        profitability_interval_seconds = Decimal(str(strategy_config.funding_profitability_interval))
        opportunities: List[Dict[str, Any]] = []
        for token in eligible_tokens:
            funding_rate_per_sec_by_connector: Dict[str, Decimal] = {}
            pair_by_connector: Dict[str, str] = {}
            for connector_name, pair_info in connector_to_pair_info_map.items():
                quote_asset = self._get_connector_quote_currency(connector_name)
                candidate_pair = f"{token}-{quote_asset}".upper()
                pair_info_entry = pair_info.get(candidate_pair)
                if pair_info_entry is not None and pair_info_entry.get("funding_rate_per_sec") is not None:
                    funding_rate_per_sec_by_connector[connector_name] = pair_info_entry["funding_rate_per_sec"]
                    pair_by_connector[connector_name] = candidate_pair
            if len(funding_rate_per_sec_by_connector) < 2:
                continue
            best_long_connector = None; best_short_connector = None; best_abs_profitability = Decimal("0")
            connector_names = list(funding_rate_per_sec_by_connector.keys())
            for i in range(len(connector_names)):
                for j in range(i + 1, len(connector_names)):
                    connector_a, connector_b = connector_names[i], connector_names[j]
                    rate_a_per_sec = funding_rate_per_sec_by_connector[connector_a]
                    rate_b_per_sec = funding_rate_per_sec_by_connector[connector_b]
                    funding_diff_value = (rate_b_per_sec - rate_a_per_sec) * profitability_interval_seconds
                    abs_diff_profitability = abs(funding_diff_value)
                    if abs_diff_profitability > best_abs_profitability:
                        best_abs_profitability = abs_diff_profitability
                        if rate_a_per_sec < rate_b_per_sec:
                            best_long_connector, best_short_connector = connector_a, connector_b
                        else:
                            best_long_connector, best_short_connector = connector_b, connector_a
            if best_long_connector is None:
                continue
            if best_abs_profitability >= Decimal(strategy_config.min_funding_rate_profitability):
                opportunities.append({
                    "token": token,
                    "long_connector": best_long_connector,
                    "short_connector": best_short_connector,
                    "long_pair": pair_by_connector[best_long_connector],
                    "short_pair": pair_by_connector[best_short_connector],
                    "profitability": best_abs_profitability,
                })
        opportunities.sort(key=lambda x: x.get("profitability", Decimal("0")), reverse=True)
        self.logger().info(f"Found {len(opportunities)} opportunities: {opportunities}")
        return opportunities

    def create_actions_proposal(self) -> List[CreateExecutorAction]:
        # Controllers produce actions; the script itself doesn't create executors
        return []

    def stop_actions_proposal(self) -> List[StopExecutorAction]:
        # No script-level stop actions; controllers handle their own
        return []

    def apply_initial_setting(self):
        # Let controllers manage leverage/position mode; nothing global here
        self._last_status_log = 0

    def on_tick(self):
        super().on_tick()

        try:
            if self._last_scan_ts == 0 or (self.current_timestamp - self._last_scan_ts) >= self.scan_interval:
                self._last_scan_ts = self.current_timestamp
                opportunities = self._scan_opportunities()
                for opportunity in opportunities:
                    token = opportunity["token"]
                    if token in self._spawned_tokens:
                        continue
                    strategy_cfg: V2CrossExchangeHedgedMMConfig = self.config

                    from controllers.market_making.cross_exchange_hedged_mm import CrossExchangeHedgedMMConfig
                    new_cfg = CrossExchangeHedgedMMConfig(
                        id=f"cross_xemm_{token}",
                        controller_name="cross_exchange_hedged_mm",
                        candles_config=strategy_cfg.candles_config,
                        max_entry_spread_pct=strategy_cfg.max_entry_spread_pct,
                        slice_amount_quote=strategy_cfg.slice_amount_quote,
                        total_slices=strategy_cfg.total_slices,
                        maker_limit_offset_pct=strategy_cfg.maker_limit_offset_pct,
                        leverage=strategy_cfg.leverage,
                        target_token=token,
                        long_connector=opportunity["long_connector"],
                        short_connector=opportunity["short_connector"],
                        long_pair=opportunity["long_pair"],
                        short_pair=opportunity["short_pair"],

                    )
                    # Schedule async provisioning + start to avoid blocking tick
                    self._spawned_tokens.add(token)
                    asyncio.create_task(self._provision_and_start_controller(new_cfg))
        except Exception as e:
            self.logger().error(f"opportunity scan/spawn error: {e}", exc_info=True)

    @classmethod
    def init_markets(cls, config: V2CrossExchangeHedgedMMConfig):
        markets = MarketDict(config.markets)
        for conn in config.connectors:
            quote = config.connectors_quotes.get(conn, "USD" if conn in USD_QUOTE_CONNECTORS else "USDT")
            markets = markets.add_or_update(conn, f"BTC-{quote.upper()}")
        cls.markets = markets

    async def _provision_and_start_controller(self, new_cfg):
        try:
            await self.ensure_markets_for_controller(new_cfg, timeout=20.0)
        except Exception as e:
            self.logger().warning(f"Failed to ensure markets for {new_cfg.id}: {e}")
        try:
            self.add_controller(new_cfg)
            ctrl = self.controllers[new_cfg.id]
            ctrl.start()
            self.logger().info(f"Controller {new_cfg.id} started")
        except Exception as e:
            self.logger().error(f"Failed to start controller {new_cfg.id}: {e}", exc_info=True)
