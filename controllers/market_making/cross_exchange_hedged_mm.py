import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from pydantic import Field

from hummingbot.core.data_type.common import MarketDict, PriceType, TradeType
from hummingbot.data_feed.candles_feed.data_types import CandlesConfig
from hummingbot.logger.logger import HummingbotLogger
from hummingbot.strategy_v2.controllers.market_making_controller_base import (
    MarketMakingControllerBase,
    MarketMakingControllerConfigBase,
)
from hummingbot.strategy_v2.executors.data_types import ConnectorPair
from hummingbot.strategy_v2.executors.sliced_hedged_order_executor.data_types import SlicedHedgedOrderExecutorConfig
from hummingbot.strategy_v2.models.executor_actions import CreateExecutorAction


class CrossExchangeHedgedMMConfig(MarketMakingControllerConfigBase):
    controller_name: str = "cross_exchange_hedged_mm"
    markets: MarketDict = Field(default_factory=MarketDict)
    # Optional: candles for order book/vol filters
    candles_config: List[CandlesConfig] = []

    # Pre-selected opportunity fields provided by the script
    target_token: Optional[str] = Field(default=None)
    long_connector: Optional[str] = Field(default=None)
    short_connector: Optional[str] = Field(default=None)
    long_pair: Optional[str] = Field(default=None)
    short_pair: Optional[str] = Field(default=None)

    # Entry filters and slicing
    # Max allowed normalized price spread between the two exchanges at entry time (e.g., 0.002 = 0.2%)
    max_entry_spread_pct: Decimal = Field(default=Decimal("0.002"), json_schema_extra={"prompt_on_new": True})
    # Per-slice budget in quote on the LONG (maker) exchange
    slice_amount_quote: Decimal = Field(default=Decimal("100"), json_schema_extra={"prompt_on_new": True})
    # Total number of sequential slices to place; next slice placed only after previous fills/cancels
    total_slices: int = Field(default=5, json_schema_extra={"prompt_on_new": True})
    # Maker limit offset relative to mid (positive tightens towards favorable, e.g., 0.0005 = 5 bps)
    maker_limit_offset_pct: Decimal = Field(default=Decimal("0.0005"), json_schema_extra={"prompt_on_new": True})

    def update_markets(self, markets: MarketDict) -> MarketDict:
        """Ensure long/short pairs are registered so their order books stream and pricing is available."""
        if self.long_connector and self.long_pair:
            markets = markets.add_or_update(self.long_connector, self.long_pair)
        if self.short_connector and self.short_pair:
            markets = markets.add_or_update(self.short_connector, self.short_pair)
        return markets


MIN_VOLUME = Decimal("1000000")


class CrossExchangeHedgedMMController(MarketMakingControllerBase):
    def __init__(self, config: CrossExchangeHedgedMMConfig, *args, **kwargs):
        super().__init__(config, *args, **kwargs)
        self.config = config
        self.processed_data = {"tokens": {}, "opportunities": []}
        # Cache of supported trading pairs per connector (uppercase HB format)
        self._supported_pairs_cache = {}
    # No per-slice state here; slicing handled by executor

    _logger = None

    @classmethod
    def logger(cls) -> HummingbotLogger:
        if cls._logger is None:
            cls._logger = logging.getLogger(__name__)
        return cls._logger

    async def update_processed_data(self):
        """Controller no longer reads files. It acts only on a pre-selected opportunity provided via config.
        If long/short fields are set (or legacy fixed_*), expose one opportunity; otherwise none.
        """
        cfg = self.config
        self.processed_data = {"tokens": {}, "opportunities": []}
        # Prefer new field names, fallback to legacy fixed_* for compatibility
        long_connector = getattr(cfg, "long_connector", None) or getattr(cfg, "fixed_long_connector", None)
        short_connector = getattr(cfg, "short_connector", None) or getattr(cfg, "fixed_short_connector", None)
        long_pair = getattr(cfg, "long_pair", None) or getattr(cfg, "fixed_long_pair", None)
        short_pair = getattr(cfg, "short_pair", None) or getattr(cfg, "fixed_short_pair", None)

        if all([long_connector, short_connector, long_pair, short_pair]):
            token = cfg.target_token or self._split_pair(long_pair)[0]  # type: ignore
            opp = {
                "token": token,
                "long_connector": long_connector,
                "short_connector": short_connector,
                "long_pair": long_pair,
                "short_pair": short_pair,
                # profitability is not used in controller gating; keep for display
                "profitability": Decimal("0"),
            }
            self.processed_data = {"tokens": {token: {}}, "opportunities": [opp]}

    def executors_to_early_stop(self):
        # No custom early stop here; rely on strategy-level controls
        return []

    def create_actions_proposal(self) -> List[CreateExecutorAction]:
        # Create at most one hedged maker+market entry per tick, sequentially slicing
        actions: List[CreateExecutorAction] = []
        opps: List[Dict[str, Any]] = self.processed_data.get("opportunities", [])
        if not opps:
            return actions

    # Choose the top opportunity that passes spread filter; slicing handled by executor
        for opp in opps:
            if not self._price_spread_ok(opp):
                continue

            # Build maker (LONG) and hedge (SHORT) legs
            long_ex = opp["long_connector"]; long_pair = opp["long_pair"]
            short_ex = opp["short_connector"]; short_pair = opp["short_pair"]

            # Price and amount for the maker order
            mid = Decimal(self.market_data_provider.get_price_by_type(long_ex, long_pair, PriceType.MidPrice))
            maker_side = TradeType.BUY
            # Favorable passive price: if BUY, place slightly below mid; if SELL, above mid (SELL unused here)
            price = mid * (Decimal("1") - self.config.maker_limit_offset_pct)
            try:
                price = self.market_data_provider.quantize_order_price(long_ex, long_pair, price)
            except Exception:
                # Fallback without quantization if trading rules unavailable
                pass

            # Convert per-slice quote into base amount using maker price
            amount_base = (self.config.slice_amount_quote / price)
            try:
                amount_base = self.market_data_provider.quantize_order_amount(long_ex, long_pair, amount_base)
            except Exception:
                pass
            if amount_base <= 0:
                continue

            hedged_cfg = SlicedHedgedOrderExecutorConfig(
                timestamp=self.market_data_provider.time(),
                maker_market=ConnectorPair(connector_name=long_ex, trading_pair=long_pair),
                hedge_market=ConnectorPair(connector_name=short_ex, trading_pair=short_pair),
                maker_side=maker_side,
                total_slices=self.config.total_slices,
                slice_amount_quote=self.config.slice_amount_quote,
                maker_limit_offset_pct=self.config.maker_limit_offset_pct,
                max_entry_spread_pct=self.config.max_entry_spread_pct,
                leverage=self.config.leverage,
                level_id=f"{opp['token']}"
            )

            actions.append(CreateExecutorAction(
                controller_id=self.config.id,
                executor_config=hedged_cfg
            ))

            break

        return actions

    def get_executor_config(self, level_id: str, price: Decimal, amount: Decimal):
        # Not used in the multi-token implementation (handled in create_actions_proposal)
        return None

    def to_format_status(self) -> List[str]:
        opps: List[Dict] = self.processed_data.get("opportunities", [])
        top = opps[:5]
        previews = ", ".join(
            f"{o.get('token')}:{o.get('profitability'):.3%} L:{o.get('long_connector')} S:{o.get('short_connector')}" for o in top
        ) if top else "no opps"
        return [
            f"Opportunities: {len(opps)} | Top: {previews}",
        ]

    # Removed all parquet/file discovery helpers; scanning is done by the script

    @staticmethod
    def _split_pair(pair: str) -> Tuple[str, str]:
        p = pair.upper()
        if "-" in p:
            base, quote = p.split("-", 1)
        elif "/" in p:
            base, quote = p.split("/", 1)
        else:
            base, quote = p, ""
        return base, quote
    # Removed per-slice state helpers; slicing handled by executor

    def _price_spread_ok(self, opp: Dict[str, Any]) -> bool:
        """Check mid-price spread between exchanges against threshold without FX conversion.
        - Bases must match.
        - Quotes must match OR both be in {USD, USDT, USDC}. When USD/USDT/USDC mix, treat them as equivalent.
        Returns True if abs((short_mid - long_mid)/long_mid) <= max_entry_spread_pct.
        """
        try:
            self.logger().info(f"Validating price spread for opportunity: {opp}")
            long_ex = opp["long_connector"]; long_pair = opp["long_pair"]
            self.logger().info(f"Long position - Connector: {long_ex}, Pair: {long_pair}")
            short_ex = opp["short_connector"]; short_pair = opp["short_pair"]
            self.logger().info(f"Short position - Connector: {short_ex}, Pair: {short_pair}")
            long_mid = Decimal(self.market_data_provider.get_price_by_type(long_ex, long_pair, PriceType.MidPrice))
            self.logger().info(f"Long mid price - Connector: {long_ex}, Pair: {long_pair}, Price: {long_mid}")
            short_mid = Decimal(self.market_data_provider.get_price_by_type(short_ex, short_pair, PriceType.MidPrice))
            self.logger().info(f"Short mid price - Connector: {short_ex}, Pair: {short_pair}, Price: {short_mid}")
            if long_mid <= 0 or short_mid <= 0:
                return False
            long_base, long_quote = self._split_pair(long_pair)
            short_base, short_quote = self._split_pair(short_pair)
            # Only comparable if same base (should be by construction)
            if long_base != short_base:
                return False
            # Quotes must match or be USD/USDT mix
            if long_quote != short_quote:
                if not {long_quote, short_quote}.issubset({"USD", "USDT", "USDC"}):
                    return False
            # Compare raw mids (no FX normalization)
            spread = abs((short_mid - long_mid) / long_mid)
            return spread <= self.config.max_entry_spread_pct
        except Exception as e:
            self.logger().error(f"Error validating price spread for opportunity {opp}: {e}", exc_info=True)
            return False

    # Removed supported pairs discovery; controller relies on pairs provided by the script
