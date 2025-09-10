import logging
from decimal import Decimal
from typing import Optional

from hummingbot.connector.connector_base import ConnectorBase, Union
from hummingbot.core.data_type.common import PriceType, TradeType
from hummingbot.core.event.events import (
    BuyOrderCompletedEvent,
    BuyOrderCreatedEvent,
    MarketOrderFailureEvent,
    OrderCancelledEvent,
    OrderFilledEvent,
    SellOrderCompletedEvent,
    SellOrderCreatedEvent,
)
from hummingbot.logger import HummingbotLogger
from hummingbot.strategy.script_strategy_base import ScriptStrategyBase
from hummingbot.strategy_v2.executors.executor_base import ExecutorBase
from hummingbot.strategy_v2.executors.hedged_order_executor.data_types import HedgedOrderExecutorConfig
from hummingbot.strategy_v2.executors.hedged_order_executor.hedged_order_executor import HedgedOrderExecutor
from hummingbot.strategy_v2.executors.sliced_hedged_order_executor.data_types import SlicedHedgedOrderExecutorConfig
from hummingbot.strategy_v2.models.base import RunnableStatus
from hummingbot.strategy_v2.models.executors import CloseType


class SlicedHedgedOrderExecutor(ExecutorBase):
    _logger = None

    @classmethod
    def logger(cls) -> HummingbotLogger:
        if cls._logger is None:
            cls._logger = logging.getLogger(__name__)
        return cls._logger

    def __init__(self, strategy: ScriptStrategyBase, config: SlicedHedgedOrderExecutorConfig,
                 update_interval: float = 0.5, max_retries: int = 10):
        super().__init__(strategy=strategy,
                         config=config,
                         connectors=[config.maker_market.connector_name, config.hedge_market.connector_name],
                         update_interval=update_interval)
        self.config: SlicedHedgedOrderExecutorConfig = config
        self._current_slice_index: int = 0
        self._active_child: Optional[HedgedOrderExecutor] = None
        self._cum_hedged_base: Decimal = Decimal("0")
        self._max_retries = max_retries
        self._retries = 0

    async def validate_sufficient_balance(self):
        # Rely on child executors to validate at placement time
        pass

    async def on_start(self):
        await super().on_start()

    async def control_task(self):
        if self.status == RunnableStatus.RUNNING:
            # If child not running, start next slice if available
            if self._active_child is None or self._active_child.is_closed:
                if self._active_child is not None:
                    # Accumulate hedged amount from child
                    try:
                        info = self._active_child.get_custom_info() or {}
                        hedged = Decimal(str(info.get("hedged_base_filled", "0")))
                        self._cum_hedged_base += hedged
                    except Exception:
                        pass
                    self._active_child = None
                    self._current_slice_index += 1

                if self._current_slice_index >= self.config.total_slices:
                    self.close_type = CloseType.POSITION_HOLD
                    self.stop()
                    return

                # Spread gate (USD/USDT treated equal if configured)
                if not self._spread_ok():
                    # Wait until spread becomes acceptable
                    return

                # Compute price and amount for this slice
                maker_ex = self.config.maker_market.connector_name
                maker_pair = self.config.maker_market.trading_pair
                mid = Decimal(self.get_price(maker_ex, maker_pair, PriceType.MidPrice))
                if mid <= 0:
                    return
                side = self.config.maker_side
                price = mid * (Decimal("1") - self.config.maker_limit_offset_pct) if side == TradeType.BUY else mid * (Decimal("1") + self.config.maker_limit_offset_pct)
                # Quantize price if possible
                try:
                    rules = self.get_trading_rules(maker_ex, maker_pair)
                    price = (price // rules.min_price_increment) * rules.min_price_increment if hasattr(rules, 'min_price_increment') else price
                except Exception:
                    pass
                amount = self.config.slice_amount_quote / price if side == TradeType.BUY else self.config.slice_amount_quote / price
                try:
                    rules = self.get_trading_rules(maker_ex, maker_pair)
                    amount = (amount // rules.min_base_amount_increment) * rules.min_base_amount_increment if hasattr(rules, 'min_base_amount_increment') else amount
                except Exception:
                    pass
                if amount <= 0:
                    return

                child_cfg = HedgedOrderExecutorConfig(
                    timestamp=self._strategy.current_timestamp,
                    maker_market=self.config.maker_market,
                    hedge_market=self.config.hedge_market,
                    maker_side=side,
                    amount=amount,
                    price=price,
                    leverage=self.config.leverage,
                    level_id =f"{self.config.level_id or ''}_slice_{self._current_slice_index + 1}"
                )
                child = HedgedOrderExecutor(self._strategy, child_cfg, update_interval=self._update_interval, max_retries=self._max_retries)
                child.start()
                self._active_child = child

        elif self.status == RunnableStatus.SHUTTING_DOWN:
            await self.control_shutdown_process()

    def _quotes_compatible(self) -> bool:
        m_base, m_quote = self.config.maker_market.trading_pair.split("-")
        h_base, h_quote = self.config.hedge_market.trading_pair.split("-")
        if m_base != h_base:
            return False
        if m_quote == h_quote:
            return True
        if self.config.treat_usd_usdt_as_equal and {m_quote.upper(), h_quote.upper()}.issubset({"USD", "USDT", "USDC"}):
            return True
        return False

    def _spread_ok(self) -> bool:
        if not self._quotes_compatible():
            return False
        maker_ex = self.config.maker_market.connector_name
        maker_pair = self.config.maker_market.trading_pair
        hedge_ex = self.config.hedge_market.connector_name
        hedge_pair = self.config.hedge_market.trading_pair
        # Prefer RateOracle via strategy.market_data_provider.get_rate
        try:
            long_mid = Decimal(str(self._strategy.market_data_provider.get_rate(maker_pair) or 0))
            short_mid = Decimal(str(self._strategy.market_data_provider.get_rate(hedge_pair) or 0))
        except Exception:
            long_mid = Decimal("0"); short_mid = Decimal("0")
        if long_mid <= 0 or short_mid <= 0:
            try:
                if long_mid <= 0:
                    long_mid = Decimal(self.get_price(maker_ex, maker_pair, PriceType.MidPrice))
                if short_mid <= 0:
                    short_mid = Decimal(self.get_price(hedge_ex, hedge_pair, PriceType.MidPrice))
            except Exception:
                return False
        if long_mid <= 0 or short_mid <= 0:
            return False
        spread = abs((short_mid - long_mid) / long_mid)
        return spread <= self.config.max_entry_spread_pct

    def process_order_created_event(self,
                                    event_tag: int,
                                    market: ConnectorBase,
                                    event: Union[BuyOrderCreatedEvent, SellOrderCreatedEvent]):
        # Forward to child if exists
        if self._active_child is not None:
            self._active_child.process_order_created_event(event_tag, market, event)

    def process_order_filled_event(self, event_tag: int, market: ConnectorBase, event: OrderFilledEvent):
        if self._active_child is not None:
            self._active_child.process_order_filled_event(event_tag, market, event)

    def process_order_canceled_event(self, event_tag: int, market: ConnectorBase, event: OrderCancelledEvent):
        if self._active_child is not None:
            self._active_child.process_order_canceled_event(event_tag, market, event)

    def process_order_completed_event(self,
                                      event_tag: int,
                                      market: ConnectorBase,
                                      event: Union[BuyOrderCompletedEvent, SellOrderCompletedEvent]):
        if self._active_child is not None:
            self._active_child.process_order_completed_event(event_tag, market, event)

    def process_order_failed_event(self, event_tag: int, market: ConnectorBase, event: MarketOrderFailureEvent):
        if self._active_child is not None:
            self._active_child.process_order_failed_event(event_tag, market, event)

    def early_stop(self, keep_position: bool = False):
        if self._active_child is not None and self._active_child.is_active:
            self._active_child.early_stop(keep_position)
        self.close_type = CloseType.EARLY_STOP
        self.stop()

    def get_cum_fees_quote(self) -> Decimal:
        return Decimal("0")

    def get_net_pnl_quote(self) -> Decimal:
        return Decimal("0")

    def get_net_pnl_pct(self) -> Decimal:
        return Decimal("0")

    def get_custom_info(self) -> dict:
        return {
            "maker_connector": self.config.maker_market.connector_name,
            "maker_trading_pair": self.config.maker_market.trading_pair,
            "hedge_connector": self.config.hedge_market.connector_name,
            "hedge_trading_pair": self.config.hedge_market.trading_pair,
            "maker_side": self.config.maker_side,
            "level_id": self.config.level_id,
            "slices_total": self.config.total_slices,
            "slices_done": self._current_slice_index,
            "cum_hedged_base_filled": self._cum_hedged_base,
        }
