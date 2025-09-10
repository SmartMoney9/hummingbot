from decimal import Decimal
from typing import Literal, Optional

from hummingbot.core.data_type.common import TradeType
from hummingbot.strategy_v2.executors.data_types import ConnectorPair, ExecutorConfigBase


class HedgedOrderExecutorConfig(ExecutorConfigBase):
    type: Literal["hedged_order_executor"] = "hedged_order_executor"
    maker_market: ConnectorPair
    hedge_market: ConnectorPair
    maker_side: TradeType
    amount: Decimal
    price: Decimal
    leverage: int = 1
    level_id: Optional[str] = None
