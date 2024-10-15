from hummingbot.core.api_throttler.data_types import LinkedLimitWeightPair, RateLimit
from hummingbot.core.data_type.in_flight_order import OrderState

DEFAULT_DOMAIN = ""

HBOT_ORDER_ID_PREFIX = "HBOT"
MAX_ORDER_ID_LEN = 32
CANDLES_ENDPOINT = "/api/v2/spot/market/candles"

# Base URLs
REST_URL = "https://api.bitget.com"
WSS_URL = "wss://ws.bitget.com/spot/v1/stream"

PING_PATH_URL = "/ping"
TICKER_BOOK_PATH_URL= ""

# API Versions
PUBLIC_API_VERSION = ""
PRIVATE_API_VERSION = ""

# Public API endpoints
TICKER_PRICE_CHANGE_PATH_URL = "/api/v2/spot/market/tickers"
SNAPSHOT_PATH_URL = "/api/spot/v1/market/depth"
EXCHANGE_INFO_PATH_URL = "/api/spot/v1/public/products"
SERVER_TIME_PATH_URL = "/api/spot/v1/public/time"
# Private API endpoints
ACCOUNTS_PATH_URL = "/api/v2/spot/account/assets"
MY_TRADES_PATH_URL = "/api/v2/spot/trade/fills"
ORDER_PATH_URL = "/api/spot/v1/trade/orders"
Bitget_USER_STREAM_PATH_URL = "/userDataStream"
WS_HEARTBEAT_TIME_INTERVAL = 30
SECONDS_TO_WAIT_TO_RECEIVE_MESSAGE = 20

# Bitget parameters
SIDE_BUY = "buy"
SIDE_SELL = "sell"

TIME_IN_FORCE_GTC = "gtc"  # Good till canceled
TIME_IN_FORCE_IOC = "ioc"  # Immediate or cancel

# Rate Limit Types
IP_REQUEST_RATE_LIMIT = "IP_REQUEST_RATE_LIMIT"
UID_REQUEST_RATE_LIMIT = "UID_REQUEST_RATE_LIMIT"

# Rate Limit time intervals
ONE_MINUTE = 60
ONE_SECOND = 1
ONE_DAY = 86400

# Rate Limits
RATE_LIMITS = [
    RateLimit(limit_id=IP_REQUEST_RATE_LIMIT, limit=60, time_interval=ONE_MINUTE),
    RateLimit(limit_id=UID_REQUEST_RATE_LIMIT, limit=30, time_interval=ONE_MINUTE),
    # Public endpoints
    RateLimit(
        limit_id=TICKER_PRICE_CHANGE_PATH_URL,
        limit=60,
        time_interval=ONE_MINUTE,
        linked_limits=[LinkedLimitWeightPair(IP_REQUEST_RATE_LIMIT, 1)],
    ),
    RateLimit(
        limit_id=SNAPSHOT_PATH_URL,
        limit=60,
        time_interval=ONE_MINUTE,
        linked_limits=[LinkedLimitWeightPair(IP_REQUEST_RATE_LIMIT, 1)],
    ),
    RateLimit(
        limit_id=EXCHANGE_INFO_PATH_URL,
        limit=60,
        time_interval=ONE_MINUTE,
        linked_limits=[LinkedLimitWeightPair(IP_REQUEST_RATE_LIMIT, 1)],
    ),
    RateLimit(
        limit_id=SERVER_TIME_PATH_URL,
        limit=60,
        time_interval=ONE_MINUTE,
        linked_limits=[LinkedLimitWeightPair(IP_REQUEST_RATE_LIMIT, 1)],
    ),
    # Private endpoints
    RateLimit(
        limit_id=ACCOUNTS_PATH_URL,
        limit=30,
        time_interval=ONE_MINUTE,
        linked_limits=[LinkedLimitWeightPair(UID_REQUEST_RATE_LIMIT, 1)],
    ),
    RateLimit(
        limit_id=MY_TRADES_PATH_URL,
        limit=30,
        time_interval=ONE_MINUTE,
        linked_limits=[LinkedLimitWeightPair(UID_REQUEST_RATE_LIMIT, 1)],
    ),
    RateLimit(
        limit_id=ORDER_PATH_URL,
        limit=30,
        time_interval=ONE_MINUTE,
        linked_limits=[LinkedLimitWeightPair(UID_REQUEST_RATE_LIMIT, 1)],
    ),
]

# Error Codes and Messages
ORDER_NOT_EXIST_ERROR_CODE = "40009"
ORDER_NOT_EXIST_MESSAGE = "Order not found"
UNKNOWN_ORDER_ERROR_CODE = "40009"
UNKNOWN_ORDER_MESSAGE = "Unknown order"
TIMESTAMP_RELATED_ERROR_CODE = "40007"
TIMESTAMP_RELATED_ERROR_MESSAGE = "Timestamp expired"

# Order States
ORDER_STATE = {
    "new": OrderState.OPEN,
    "partially_filled": OrderState.PARTIALLY_FILLED,
    "filled": OrderState.FILLED,
    "canceled": OrderState.CANCELED,
    "rejected": OrderState.FAILED,
    "expired": OrderState.FAILED,
}

# WebSocket Order States
WS_ORDER_STATE = {
    "1": OrderState.OPEN,
    "2": OrderState.PARTIALLY_FILLED,
    "3": OrderState.FILLED,
    "4": OrderState.CANCELED,
    "5": OrderState.OPEN,  # Pending cancel
    "6": OrderState.FAILED,  # Rejected
    "7": OrderState.FAILED,  # Expired
}

# WebSocket Event Types
DIFF_EVENT_TYPE = "depth"
TRADE_EVENT_TYPE = "trade"

USER_TRADES_ENDPOINT_NAME =  "/api/spot/v1/market/fills"
USER_ORDERS_ENDPOINT_NAME = "/api/spot/v1/trade/orders"
USER_BALANCE_ENDPOINT_NAME = "/api/v2/spot/account/assets"
WS_CONNECTION_TIME_INTERVAL = 20
RATE_LIMITS = [
    RateLimit(limit_id=IP_REQUEST_RATE_LIMIT, limit=1200, time_interval=ONE_MINUTE),
    RateLimit(limit_id=UID_REQUEST_RATE_LIMIT, limit=900, time_interval=ONE_MINUTE),
    # Weighted Limits
    RateLimit(
        limit_id=TICKER_PRICE_CHANGE_PATH_URL,
        limit=1200,
        time_interval=ONE_MINUTE,
        linked_limits=[LinkedLimitWeightPair(IP_REQUEST_RATE_LIMIT, 1)]
    ),
    RateLimit(
        limit_id=SNAPSHOT_PATH_URL,
        limit=1200,
        time_interval=ONE_MINUTE,
        linked_limits=[LinkedLimitWeightPair(IP_REQUEST_RATE_LIMIT, 1)]
    ),
    RateLimit(
        limit_id=EXCHANGE_INFO_PATH_URL,
        limit=1200,
        time_interval=ONE_MINUTE,
        linked_limits=[LinkedLimitWeightPair(IP_REQUEST_RATE_LIMIT, 1)]
    ),
    RateLimit(
        limit_id=SERVER_TIME_PATH_URL,
        limit=1200,
        time_interval=ONE_MINUTE,
        linked_limits=[LinkedLimitWeightPair(IP_REQUEST_RATE_LIMIT, 1)]
    ),
    RateLimit(
        limit_id=ACCOUNTS_PATH_URL,
        limit=900,
        time_interval=ONE_MINUTE,
        linked_limits=[LinkedLimitWeightPair(UID_REQUEST_RATE_LIMIT, 1)]
    ),
    RateLimit(
        limit_id=MY_TRADES_PATH_URL,
        limit=900,
        time_interval=ONE_MINUTE,
        linked_limits=[LinkedLimitWeightPair(UID_REQUEST_RATE_LIMIT, 1)]
    ),
    RateLimit(
        limit_id=ORDER_PATH_URL,
        limit=900,
        time_interval=ONE_MINUTE,
        linked_limits=[LinkedLimitWeightPair(UID_REQUEST_RATE_LIMIT, 1)]
    ),
]

