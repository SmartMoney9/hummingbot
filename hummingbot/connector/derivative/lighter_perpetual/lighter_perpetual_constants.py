from hummingbot.core.api_throttler.data_types import LinkedLimitWeightPair, RateLimit
from hummingbot.core.data_type.in_flight_order import OrderState

BASE_TICKERS = ["BTC", "ETH", "SOL"]

EXCHANGE_NAME = "hyperliquid_perpetual"
BROKER_ID = "HBOT"
MAX_ORDER_ID_LEN = None

MARKET_ORDER_SLIPPAGE = 0.05

DOMAIN = EXCHANGE_NAME
TESTNET_DOMAIN = "hyperliquid_perpetual_testnet"

PERPETUAL_BASE_URL = "https://mainnet.zklighter.elliot.ai"

TESTNET_BASE_URL = "https://mainnet.zklighter.elliot.ai"

PERPETUAL_WS_URL = "wss://api.hyperliquid.xyz/ws"

TESTNET_WS_URL = "wss://api.hyperliquid-testnet.xyz/ws"

FUNDING_RATE_UPDATE_INTERNAL_SECOND = 60

CURRENCY = "USD"

META_INFO = "meta"

ASSET_CONTEXT_TYPE = "metaAndAssetCtxs"

TRADES_TYPE = "userFills"

ORDER_STATUS_TYPE = "orderStatus"

USER_STATE_TYPE = "clearinghouseState"

# yes
TICKER_PRICE_CHANGE_URL = "/info"
# yes
SNAPSHOT_REST_URL = "/info"

EXCHANGE_INFO_URL = "/info"

ORDER_BOOKS_URL = "/api/v1/orderBooks"

ORDER_BOOK_DETAILS_URL = "/api/v1/orderBookDetails"

ORDER_BOOK_ORDERS_URL = "/api/v1/orderBookOrders"

FUNDING_URL = "/api/v1/funding-rates"

CANCEL_ORDER_URL = "/exchange"

CREATE_ORDER_URL = "/exchange"

ACCOUNT_TRADE_LIST_URL = "/info"

ORDER_URL = "/info"

ACCOUNT_INFO_URL = "/api/v1/account"

POSITION_INFORMATION_URL = "/info"

SET_LEVERAGE_URL = "/exchange"

GET_LAST_FUNDING_RATE_PATH_URL = "/info"

PING_URL = "/"

TRADES_ENDPOINT_NAME = "trades"
DEPTH_ENDPOINT_NAME = "l2Book"


USER_ORDERS_ENDPOINT_NAME = "orderUpdates"
USEREVENT_ENDPOINT_NAME = "user"

# Order Statuses
ORDER_STATE = {
    "open": OrderState.OPEN,
    "resting": OrderState.OPEN,
    "filled": OrderState.FILLED,
    "canceled": OrderState.CANCELED,
    "rejected": OrderState.FAILED,
    "reduceOnlyCanceled": OrderState.CANCELED,
    "perpMarginRejected": OrderState.FAILED,
}

HEARTBEAT_TIME_INTERVAL = 30.0

MAX_REQUEST = 1_200
ALL_ENDPOINTS_LIMIT = "All"
MAX_REQUESTS_PER_MIN = 60  # Standard account
ONE_MIN = 60

RATE_LIMITS = [
    RateLimit(ALL_ENDPOINTS_LIMIT, limit=MAX_REQUEST, time_interval=60),

    # Weight Limits for individual endpoints
    RateLimit(limit_id=SNAPSHOT_REST_URL, limit=MAX_REQUEST, time_interval=60,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)]),
    RateLimit(limit_id=TICKER_PRICE_CHANGE_URL, limit=MAX_REQUEST, time_interval=60,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)]),
    RateLimit(limit_id=EXCHANGE_INFO_URL, limit=MAX_REQUEST, time_interval=60,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)]),
    RateLimit(limit_id=PING_URL, limit=MAX_REQUEST, time_interval=60,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)]),
    RateLimit(limit_id=ORDER_URL, limit=MAX_REQUEST, time_interval=60,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)]),
    RateLimit(limit_id=CREATE_ORDER_URL, limit=MAX_REQUEST, time_interval=60,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)]),
    RateLimit(limit_id=CANCEL_ORDER_URL, limit=MAX_REQUEST, time_interval=60,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)]),

    RateLimit(limit_id=ACCOUNT_TRADE_LIST_URL, limit=MAX_REQUEST, time_interval=60,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)]),
    RateLimit(limit_id=SET_LEVERAGE_URL, limit=MAX_REQUEST, time_interval=60,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)]),
    RateLimit(limit_id=ACCOUNT_INFO_URL, limit=MAX_REQUEST, time_interval=60,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)]),
    RateLimit(limit_id=POSITION_INFORMATION_URL, limit=MAX_REQUEST, time_interval=60,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)]),
    RateLimit(limit_id=GET_LAST_FUNDING_RATE_PATH_URL, limit=MAX_REQUEST, time_interval=60,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)]),

    # Global IP/User limit
    RateLimit(limit_id=ALL_ENDPOINTS_LIMIT, limit=MAX_REQUESTS_PER_MIN, time_interval=ONE_MIN),

    # Weight 1
    RateLimit(limit_id="/", limit=MAX_REQUESTS_PER_MIN, time_interval=ONE_MIN, weight=1,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)]),
    RateLimit(limit_id="/info", limit=MAX_REQUESTS_PER_MIN, time_interval=ONE_MIN, weight=1,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)]),
    RateLimit(limit_id="/api/v1/sendTx", limit=MAX_REQUESTS_PER_MIN, time_interval=ONE_MIN, weight=1,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)]),
    RateLimit(limit_id="/api/v1/sendTxBatch", limit=MAX_REQUESTS_PER_MIN, time_interval=ONE_MIN, weight=1,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)]),
    RateLimit(limit_id="/api/v1/nextNonce", limit=MAX_REQUESTS_PER_MIN, time_interval=ONE_MIN, weight=1,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)]),
    RateLimit(limit_id="/api/v1/orderBooks", limit=MAX_REQUESTS_PER_MIN, time_interval=ONE_MIN, weight=1,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)]),
    RateLimit(limit_id="/api/v1/orderBookDetails", limit=MAX_REQUESTS_PER_MIN, time_interval=ONE_MIN, weight=1,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)]),
    RateLimit(limit_id="/api/v1/funding-rates", limit=MAX_REQUESTS_PER_MIN, time_interval=ONE_MIN, weight=1,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)]),

    # Weight 5
    RateLimit(limit_id="/api/v1/publicPools", limit=MAX_REQUESTS_PER_MIN, time_interval=ONE_MIN, weight=5,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)]),
    RateLimit(limit_id="/api/v1/txFromL1TxHash", limit=MAX_REQUESTS_PER_MIN, time_interval=ONE_MIN, weight=5,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)]),
    RateLimit(limit_id="/api/v1/candlesticks", limit=MAX_REQUESTS_PER_MIN, time_interval=ONE_MIN, weight=5,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)]),

    # Weight 10
    RateLimit(limit_id="/api/v1/accountInactiveOrders", limit=MAX_REQUESTS_PER_MIN, time_interval=ONE_MIN, weight=10,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)]),
    RateLimit(limit_id="/api/v1/deposit/latest", limit=MAX_REQUESTS_PER_MIN, time_interval=ONE_MIN, weight=10,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)]),
    RateLimit(limit_id="/api/v1/pnl", limit=MAX_REQUESTS_PER_MIN, time_interval=ONE_MIN, weight=10,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)]),

    # Weight 15
    RateLimit(limit_id="/api/v1/apikeys", limit=MAX_REQUESTS_PER_MIN, time_interval=ONE_MIN, weight=15,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)]),

    RateLimit(limit_id="OTHER_ENDPOINTS", limit=MAX_REQUESTS_PER_MIN, time_interval=ONE_MIN, weight=30,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_LIMIT)]),

]
ORDER_NOT_EXIST_MESSAGE = "order"
UNKNOWN_ORDER_MESSAGE = "Order was never placed, already canceled, or filled"
