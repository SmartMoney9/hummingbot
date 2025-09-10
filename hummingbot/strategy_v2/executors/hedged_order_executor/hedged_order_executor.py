import logging
from decimal import Decimal
from typing import Dict, Optional

from hummingbot.connector.connector_base import ConnectorBase, Union
from hummingbot.core.data_type.common import OrderType, PositionAction, TradeType
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
from hummingbot.strategy_v2.models.base import RunnableStatus
from hummingbot.strategy_v2.models.executors import CloseType, TrackedOrder


class HedgedOrderExecutor(ExecutorBase):
    _logger = None

    @classmethod
    def logger(cls) -> HummingbotLogger:
        if cls._logger is None:
            cls._logger = logging.getLogger(__name__)
        return cls._logger

    def __init__(self, strategy: ScriptStrategyBase, config: HedgedOrderExecutorConfig,
                 update_interval: float = 0.5, max_retries: int = 10):
        super().__init__(strategy=strategy,
                         config=config,
                         connectors=[config.maker_market.connector_name, config.hedge_market.connector_name],
                         update_interval=update_interval)
        self.config = config
        self._maker_order: Optional[TrackedOrder] = None
        self._current_retries = 0
        self._max_retries = max_retries
        self._hedged_base_filled: Decimal = Decimal("0")

    async def validate_sufficient_balance(self):
        # Basic balance check on maker side; hedge will be market so we assume budget_checker on taker side at runtime
        amount = self.config.amount
        price = self.config.price
        base, quote = self.config.maker_market.trading_pair.split("-")
        if self.is_perpetual_connector(self.config.maker_market.connector_name):
            # rely on exchange budget checker at order placement
            pass
        else:
            if self.config.maker_side == TradeType.BUY:
                available = self.get_available_balance(self.config.maker_market.connector_name, quote)
                if available < amount * price:
                    self.close_type = CloseType.INSUFFICIENT_BALANCE
                    self.logger().error("Insufficient quote balance for maker order.")
                    self.stop()
            else:
                available = self.get_available_balance(self.config.maker_market.connector_name, base)
                if available < amount:
                    self.close_type = CloseType.INSUFFICIENT_BALANCE
                    self.logger().error("Insufficient base balance for maker order.")
                    self.stop()

    async def control_task(self):
        if self.status == RunnableStatus.RUNNING:
            if self._maker_order is None:
                self.place_maker_order()
        elif self.status == RunnableStatus.SHUTTING_DOWN:
            await self.control_shutdown_process()

    def place_maker_order(self):
        maker_connector = self.connectors[self.config.maker_market.connector_name]
        supported = maker_connector.supported_order_types() if hasattr(maker_connector, "supported_order_types") else []
        maker_order_type = OrderType.LIMIT_MAKER if OrderType.LIMIT_MAKER in supported else OrderType.LIMIT
        order_id = self.place_order(
            connector_name=self.config.maker_market.connector_name,
            trading_pair=self.config.maker_market.trading_pair,
            order_type=maker_order_type,
            side=self.config.maker_side,
            amount=self.config.amount,
            price=self.config.price,
            position_action=PositionAction.OPEN,
        )
        self._maker_order = TrackedOrder(order_id=order_id)

    def place_hedge_market(self, base_amount: Decimal):
        hedge_side = TradeType.SELL if self.config.maker_side == TradeType.BUY else TradeType.BUY
        self.place_order(
            connector_name=self.config.hedge_market.connector_name,
            trading_pair=self.config.hedge_market.trading_pair,
            order_type=OrderType.MARKET,
            side=hedge_side,
            amount=base_amount,
            position_action=PositionAction.OPEN,
        )

    def process_order_created_event(self,
                                    event_tag: int,
                                    market: ConnectorBase,
                                    event: Union[BuyOrderCreatedEvent, SellOrderCreatedEvent]):
        if self._maker_order and event.order_id == self._maker_order.order_id:
            self._maker_order.order = self.get_in_flight_order(self.config.maker_market.connector_name, event.order_id)

    def process_order_filled_event(self, event_tag: int, market: ConnectorBase, event: OrderFilledEvent):
        if self._maker_order and event.order_id == self._maker_order.order_id:
            self._maker_order.order = self.get_in_flight_order(self.config.maker_market.connector_name, event.order_id)
            # Determine newly filled amount in base
            newly_filled = self._maker_order.executed_amount_base - self._hedged_base_filled
            if newly_filled > Decimal("0"):
                self.place_hedge_market(newly_filled)
                self._hedged_base_filled += newly_filled

    def process_order_canceled_event(self, event_tag: int, market: ConnectorBase, event: OrderCancelledEvent):
        if self._maker_order and event.order_id == self._maker_order.order_id:
            # If any partial fill occurred, we already hedged it; stop executor
            self.close_type = CloseType.POSITION_HOLD
            self.stop()

    def process_order_completed_event(self,
                                      event_tag: int,
                                      market: ConnectorBase,
                                      event: Union[BuyOrderCompletedEvent, SellOrderCompletedEvent]):
        if self._maker_order and event.order_id == self._maker_order.order_id:
            self._maker_order.order = self.get_in_flight_order(self.config.maker_market.connector_name, event.order_id)
            # Safety: if any residual unhedged base exists, hedge it now
            residual = self._maker_order.executed_amount_base - self._hedged_base_filled
            if residual > Decimal("0"):
                self.place_hedge_market(residual)
                self._hedged_base_filled += residual
            self.close_type = CloseType.POSITION_HOLD
            self.stop()

    def process_order_failed_event(self, event_tag: int, market: ConnectorBase, event: MarketOrderFailureEvent):
        if self._maker_order and event.order_id == self._maker_order.order_id:
            self._current_retries += 1
            if self._current_retries > self._max_retries:
                self.close_type = CloseType.EARLY_STOP
                self.stop()

    def early_stop(self, keep_position: bool = False):
        self.close_type = CloseType.EARLY_STOP
        self.stop()

    def get_cum_fees_quote(self) -> Decimal:
        return Decimal("0")

    def get_net_pnl_quote(self) -> Decimal:
        return Decimal("0")

    def get_net_pnl_pct(self) -> Decimal:
        return Decimal("0")

    def get_custom_info(self) -> Dict:
        return {
            "maker_connector": self.config.maker_market.connector_name,
            "maker_trading_pair": self.config.maker_market.trading_pair,
            "hedge_connector": self.config.hedge_market.connector_name,
            "hedge_trading_pair": self.config.hedge_market.trading_pair,
            "maker_side": self.config.maker_side,
            "level_id": self.config.level_id,
            "hedged_base_filled": self._hedged_base_filled,
        }
