from decimal import Decimal
from typing import Literal, Optional

from hummingbot.core.data_type.common import TradeType
from hummingbot.strategy_v2.executors.data_types import ConnectorPair, ExecutorConfigBase


class SlicedHedgedOrderExecutorConfig(ExecutorConfigBase):
    type: Literal["sliced_hedged_order_executor"] = "sliced_hedged_order_executor"
    maker_market: ConnectorPair
    hedge_market: ConnectorPair
    maker_side: TradeType = TradeType.BUY
    total_slices: int = 1
    slice_amount_quote: Decimal = Decimal("0")
    maker_limit_offset_pct: Decimal = Decimal("0")
    max_entry_spread_pct: Decimal = Decimal("0.002")
    treat_usd_usdt_as_equal: bool = True
    leverage: int = 1
    level_id: Optional[str] = None
