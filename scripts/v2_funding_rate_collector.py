import os
import asyncio
import time
from collections import deque
from typing import Dict, List, Set, Optional, Deque

try:
    from hummingbot.connector.derivative.hyperliquid_perpetual import hyperliquid_perpetual_constants as HL_CONSTANTS
except Exception:
    HL_CONSTANTS = None

from pydantic import Field, field_validator

from hummingbot.connector.connector_base import ConnectorBase
from hummingbot.core.clock import Clock
from hummingbot.strategy.strategy_v2_base import StrategyV2Base, StrategyV2ConfigBase
from hummingbot.core.utils.async_utils import safe_ensure_future


class FundingRateCollectorConfig(StrategyV2ConfigBase):
    """Configuration for FundingRateCollector script.

    This script collects funding rate information for ALL trading pairs available
    in the specified perpetual connectors and appends the data to per-connector CSV files.
    """
    script_file_name: str = os.path.basename(__file__)
    markets: Dict[str, Set[str]] = {}
    candles_config: List = []
    controllers_config: List[str] = []

    connectors: Set[str] = Field(
        default="hyperliquid_perpetual,bybit_perpetual",
        json_schema_extra={
            "prompt": lambda mi: "Enter connectors (comma separated, e.g. hyperliquid_perpetual,bybit_perpetual): ",
            "prompt_on_new": True,
        },
    )
    polling_interval: int = Field(
        default=60,
        json_schema_extra={
            "prompt": lambda mi: "Enter funding polling interval in seconds (e.g. 60): ",
            "prompt_on_new": True,
        },
    )
    output_dir: str = Field(
        default="data/funding_rates",
        json_schema_extra={
            "prompt": lambda mi: "Enter output directory for funding CSV files (e.g. data/funding_rates): ",
            "prompt_on_new": True,
        },
    )
    max_pairs_per_cycle: int = Field(
        default=1000,
        json_schema_extra={
            "prompt": lambda mi: "Max pairs per connector per cycle (round-robin, e.g. 150): ",
            "prompt_on_new": True,
        },
    )
    use_hyperliquid_batch: bool = Field(
        default=True,
        json_schema_extra={
            "prompt": lambda mi: "Use single batch endpoint for Hyperliquid (True/False): ",
            "prompt_on_new": True,
        },
    )

    @field_validator("connectors", mode="before")
    @classmethod
    def parse_connectors(cls, v):
        if isinstance(v, str):
            return {c.strip() for c in v.split(",") if c.strip()}
        return v


class FundingRateCollector(StrategyV2Base):
    """Strategy script that periodically collects funding rates for all available pairs.

    Workflow:
    1. On start(): schedule async discovery of all trading pairs per connector.
    2. Filter pairs optionally by quote asset.
    3. Periodically (polling_interval) fetch funding info via connector.get_funding_info(trading_pair).
    4. Append rows to CSV file per connector: <output_dir>/<connector>_funding_rates.csv.
    5. Each row: timestamp, trading_pair, rate, funding_interval, next_funding_utc_timestamp.
    """

    def __init__(self, connectors: Dict[str, ConnectorBase], config: FundingRateCollectorConfig):
        super().__init__(connectors, config)
        self.config = config
        self._connector_pairs = {name: [] for name in self.config.connectors}
        self._funding_task = None
        self._discovery_tasks = []
        self._discovery_attempted = set()
        self._discovery_completed = set()
        os.makedirs(self.config.output_dir, exist_ok=True)
        self._poll_offsets = {}
        self._collecting = False


    @classmethod
    def init_markets(cls, config: FundingRateCollectorConfig):  # type: ignore
        """Provide a minimal markets mapping so Hummingbot instantiates the requested connectors.

        If the user did not specify markets, we synthesize one placeholder pair per connector.
        Later, we discover the full list via all_trading_pairs().
        """
        if config.markets:
            cls.markets = config.markets
            return

        placeholder_map = {
            "bybit_perpetual": "BTC-USDT",
            "hyperliquid_perpetual": "BTC-USD",
            "lighter_perpetual": "BTC-USD",
        }
        synthesized: Dict[str, Set[str]] = {}
        for name in config.connectors:
            placeholder = placeholder_map.get(name)
            if placeholder is None:
                placeholder = "BTC-USDT"
            synthesized[name] = {placeholder}
        cls.markets = synthesized

    def start(self, clock: Clock, timestamp: float) -> None:
        self._last_timestamp = timestamp
        self._funding_task = safe_ensure_future(self._poll_funding_loop())

    def on_tick(self):
        """Override to trigger a single discovery per connector once it's ready."""
        super().on_tick()
        if not self.ready_to_trade:
            return
        for connector_name in self.config.connectors:
            if connector_name in self._discovery_attempted:
                continue  # already attempted (one-shot per requirement)
            connector = self.connectors.get(connector_name)
            if connector is None:
                self.logger().warning(f"[FUNDING-COLLECTOR] Configured connector '{connector_name}' not found.")
                self._discovery_attempted.add(connector_name)
                continue
            if not connector.ready:
                # Wait until connector.ready before attempting (no spam)
                continue
            self._discovery_attempted.add(connector_name)
            task = safe_ensure_future(self._discover_pairs(connector_name, connector))
            self._discovery_tasks.append(task)

    async def _discover_pairs(self, connector_name: str, connector: ConnectorBase):
        try:
            all_pairs = await connector.all_trading_pairs()
            self.logger().info(f"[FUNDING-COLLECTOR] {connector_name}: one-time discovery returned {len(all_pairs)} raw pairs.")
            unique_pairs = sorted(set(all_pairs))
            self._connector_pairs[connector_name] = unique_pairs
            self.logger().info(f"[FUNDING-COLLECTOR] {connector_name}: discovered {len(unique_pairs)} trading pairs for monitoring.")
            if len(unique_pairs) == 0:
                self.logger().warning(
                    f"[FUNDING-COLLECTOR] {connector_name}: discovery returned 0 pairs (no further retries as per one-shot configuration)."
                )
            else:
                self._discovery_completed.add(connector_name)
                # Kick off an immediate funding collection so we don't wait a full polling interval.
                safe_ensure_future(self._collect_all())
        except Exception as e:
            self.logger().warning(f"[FUNDING-COLLECTOR] {connector_name}: discovery failed with error: {e} (no retry).")

    async def _poll_funding_loop(self):
        while True:
            try:
                await self._collect_all()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.logger().warning(f"[FUNDING-COLLECTOR] Error during collection cycle: {e}")
            await asyncio.sleep(self.config.polling_interval)

    async def _collect_all(self):
        if not self.ready_to_trade:
            return
        # Prevent overlapping full-connector collection cycles (could cause duplicate CSV rows)
        if self._collecting:
            return
        self._collecting = True
        timestamp = self.current_timestamp
        try:
            for connector_name, pairs in self._connector_pairs.items():
                connector = self.connectors.get(connector_name)
                if connector is None or not pairs:
                    if connector is not None and len(pairs) == 0:
                        self.logger().info(f"[FUNDING-COLLECTOR] {connector_name}: no pairs yet to collect funding.")
                    continue
                rows: List[str] = []

                # Hyperliquid optimized batch path (optional)
                if (connector_name == "hyperliquid_perpetual" and HL_CONSTANTS is not None
                        and getattr(self.config, 'use_hyperliquid_batch', True)):
                    try:
                        data = await connector._api_post(path_url=HL_CONSTANTS.EXCHANGE_INFO_URL, data={"type": HL_CONSTANTS.ASSET_CONTEXT_TYPE})  # type: ignore
                        universe = data[0].get("universe", []) if isinstance(data, list) and len(data) > 0 else []
                        metrics = data[1] if isinstance(data, list) and len(data) > 1 else []
                        coin_map = {}
                        for idx, item in enumerate(universe):
                            try:
                                coin_map[item.get("name")] = metrics[idx]
                            except Exception:
                                continue
                        next_funding = int(((time.time() // 3600) + 1) * 3600)
                        for tp in pairs:
                            base = tp.split("-")[0]
                            m = coin_map.get(base)
                            if not m:
                                continue
                            rate = m.get("funding")
                            if rate is None:
                                continue
                            rows.append(f"{int(timestamp)},{tp},{rate},3600,{next_funding}")
                        if rows:
                            file_path = os.path.join(self.config.output_dir, f"{connector_name}_funding_rates.csv")
                            file_exists = os.path.isfile(file_path)
                            with open(file_path, 'a') as f:
                                if not file_exists:
                                    f.write("timestamp,trading_pair,rate,funding_interval,next_funding_utc_timestamp\n")
                                f.write("\n".join(rows) + "\n")
                            self.logger().info(f"[FUNDING-COLLECTOR] {connector_name}: appended {len(rows)} funding rows (batch).")
                        else:
                            self.logger().warning(f"[FUNDING-COLLECTOR] {connector_name}: batch funding produced 0 rows.")
                        continue  # proceed to next connector after batch path
                    except Exception as e:
                        self.logger().warning(f"[FUNDING-COLLECTOR] {connector_name}: batch funding error {e}.")
                        continue

                # Other connectors: round-robin slice + throttled async fetch
                max_pairs_cycle = max(1, getattr(self.config, 'max_pairs_per_cycle', len(pairs)))
                if len(pairs) > max_pairs_cycle:
                    offset = self._poll_offsets.get(connector_name, 0)
                    end = offset + max_pairs_cycle
                    if end <= len(pairs):
                        target_pairs = pairs[offset:end]
                    else:
                        target_pairs = pairs[offset:] + pairs[:end - len(pairs)]
                    self._poll_offsets[connector_name] = end % len(pairs)
                    self.logger().info(f"[FUNDING-COLLECTOR] {connector_name}: polling {len(target_pairs)} pairs this cycle (offset {offset}/{len(pairs)}).")
                else:
                    target_pairs = pairs

                orderbook_ds = getattr(connector, "_orderbook_ds", None)
                use_async_ds = orderbook_ds is not None and hasattr(orderbook_ds, "get_funding_info")

                async def fetch_funding(tp: str):
                    try:
                        if use_async_ds:
                            result = await orderbook_ds.get_funding_info(tp)  # type: ignore
                        else:
                            result = connector.get_funding_info(tp)
                        return tp, result, None
                    except Exception as e:
                        return tp, None, e

                tasks = [fetch_funding(tp) for tp in target_pairs]
                # Batch size: static moderate chunk (avoid huge gather); adjustable if needed
                batch_size = 200
                errors_this_cycle = 0
                attempts_this_cycle = 0
                for i in range(0, len(tasks), batch_size):
                    batch = tasks[i:i + batch_size]
                    try:
                        results = await asyncio.gather(*batch, return_exceptions=True)
                    except Exception as e:
                        self.logger().warning(f"[FUNDING-COLLECTOR] {connector_name}: funding batch error: {e}")
                        continue
                    for item in results:
                        if isinstance(item, Exception) or item is None:
                            continue
                        try:
                            tp, result, err = item
                        except Exception:
                            continue
                        attempts_this_cycle += 1
                        if err is not None or result is None:
                            errors_this_cycle += 1
                            continue
                        rate = getattr(result, 'rate', None)
                        if rate is None:
                            continue
                        funding_interval = getattr(result, 'funding_interval', None)
                        next_funding = getattr(result, 'next_funding_utc_timestamp', None)
                        rows.append(f"{int(timestamp)},{tp},{rate},{funding_interval},{next_funding}")
                # Simple visibility if we encountered errors.
                if errors_this_cycle and attempts_this_cycle:
                    self.logger().info(
                        f"[FUNDING-COLLECTOR] {connector_name}: {errors_this_cycle}/{attempts_this_cycle} funding fetch errors this cycle.")
                if rows:
                    file_path = os.path.join(self.config.output_dir, f"{connector_name}_funding_rates.csv")
                    file_exists = os.path.isfile(file_path)
                    with open(file_path, 'a') as f:
                        if not file_exists:
                            f.write("timestamp,trading_pair,rate,funding_interval,next_funding_utc_timestamp\n")
                        f.write("\n".join(rows) + "\n")
                    self.logger().info(f"[FUNDING-COLLECTOR] {connector_name}: appended {len(rows)} funding rows.")
                else:
                    self.logger().info(f"[FUNDING-COLLECTOR] {connector_name}: no funding rows this cycle.")
        finally:
            self._collecting = False

    async def on_stop(self):
        if self._funding_task is not None:
            self._funding_task.cancel()
            try:
                await self._funding_task
            except Exception:
                pass
        for t in self._discovery_tasks:
            if not t.done():
                t.cancel()
        if self._discovery_tasks:
            await asyncio.gather(*self._discovery_tasks, return_exceptions=True)
        await super().on_stop()

    # Override abstract methods from StrategyV2Base with no-op implementations
    def create_actions_proposal(self):  # type: ignore
        return []

    def stop_actions_proposal(self):  # type: ignore
        return []

    def store_actions_proposal(self):  # type: ignore
        return []

    def format_status(self) -> str:
        discovered = {k: len(v) for k, v in self._connector_pairs.items()}
        lines = ["Funding Rate Collector", f"Pairs discovered: {discovered}"]
        return "\n".join(lines)
