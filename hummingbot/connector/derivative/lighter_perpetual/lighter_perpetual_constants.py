from hummingbot.core.api_throttler.data_types import LinkedLimitWeightPair, RateLimit
from hummingbot.core.data_type.in_flight_order import OrderState

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

ACCOUNT_BY_L1_ADDRESS_URL = "/api/v1/accountsByL1Address"

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

POSITION_FUNDING_URL = "/api/v1/positionFunding"

PING_URL = "/"

TRADES_ENDPOINT_NAME = "trades"
DEPTH_ENDPOINT_NAME = "l2Book"


USER_ORDERS_ENDPOINT_NAME = "orderUpdates"
USEREVENT_ENDPOINT_NAME = "user"
ACCOUNT_ALL_POSITIONS_CHANNEL_PREFIX = "account_all_positions"

HEARTBEAT_TIME_INTERVAL = 30.0

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

MAX_REQUESTS_PER_MIN_STANDARD = 4000     # IP-level (Premium)
# MAX_REQUESTS_PER_MIN_PREMIUM = 60  # IP-level (Standard)

ALL_ENDPOINTS_IP = "All_IP"
ONE_MIN = 60

RATE_LIMITS = [
    # Глобальний IP-ліміт
    RateLimit(limit_id=ALL_ENDPOINTS_IP, limit=MAX_REQUESTS_PER_MIN_STANDARD, time_interval=ONE_MIN),

    # === Пер-юзер ліміти за групами з доки ===
    # 6 rpm: sendTx / sendTxBatch / nextNonce
    RateLimit(limit_id="/api/v1/sendTx",       limit=6,   time_interval=ONE_MIN,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_IP)]),
    RateLimit(limit_id="/api/v1/sendTxBatch",  limit=6,   time_interval=ONE_MIN,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_IP)]),
    RateLimit(limit_id="/api/v1/nextNonce",    limit=6,   time_interval=ONE_MIN,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_IP)]),

    # 10 rpm: /, /info
    RateLimit(limit_id="/",     limit=10, time_interval=ONE_MIN,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_IP)]),
    RateLimit(limit_id="/info", limit=10, time_interval=ONE_MIN,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_IP)]),

    # 50 rpm: publicPools, txFromL1TxHash, candlesticks
    RateLimit(limit_id="/api/v1/publicPools",     limit=50, time_interval=ONE_MIN,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_IP)]),
    RateLimit(limit_id="/api/v1/txFromL1TxHash",  limit=50, time_interval=ONE_MIN,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_IP)]),
    RateLimit(limit_id="/api/v1/candlesticks",    limit=50, time_interval=ONE_MIN,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_IP)]),

    # 100 rpm: accountInactiveOrders, deposit/latest, pnl
    RateLimit(limit_id="/api/v1/accountInactiveOrders", limit=100, time_interval=ONE_MIN,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_IP)]),
    RateLimit(limit_id="/api/v1/deposit/latest",        limit=100, time_interval=ONE_MIN,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_IP)]),
    RateLimit(limit_id="/api/v1/pnl",                   limit=100, time_interval=ONE_MIN,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_IP)]),

    # 150 rpm: apikeys
    RateLimit(limit_id="/api/v1/apikeys", limit=150, time_interval=ONE_MIN,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_IP)]),

    # 300 rpm: інші ендпоінти, що не в списку доки
    # (приклади з твого конектора)
    RateLimit(limit_id="/api/v1/orderBooks",          limit=300, time_interval=ONE_MIN,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_IP)]),
    RateLimit(limit_id="/api/v1/orderBookDetails",    limit=300, time_interval=ONE_MIN,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_IP)]),
    RateLimit(limit_id="/api/v1/orderBookOrders",     limit=300, time_interval=ONE_MIN,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_IP)]),
    RateLimit(limit_id="/api/v1/funding-rates",       limit=300, time_interval=ONE_MIN,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_IP)]),
    RateLimit(limit_id="/api/v1/positionFunding",     limit=300, time_interval=ONE_MIN,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_IP)]),
    RateLimit(limit_id="/api/v1/account",             limit=300, time_interval=ONE_MIN,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_IP)]),

    # Якщо використовуєш власні роут-и типу "/exchange" (створення/скасування ордерів),
    # ЗРОЗУМІЙ, який бек реально викликається. Якщо під капотом це sendTx — став 6 rpm.
    RateLimit(limit_id="/exchange", limit=6, time_interval=ONE_MIN,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_IP)]),

    # Для всіх інших "інфо"-роутів, що не перераховані, — 300 rpm за замовчуванням:
    RateLimit(limit_id="OTHER_ENDPOINTS", limit=300, time_interval=ONE_MIN,
              linked_limits=[LinkedLimitWeightPair(ALL_ENDPOINTS_IP)]),
]

ORDER_NOT_EXIST_MESSAGE = "order"
UNKNOWN_ORDER_MESSAGE = "Order was never placed, already canceled, or filled"
