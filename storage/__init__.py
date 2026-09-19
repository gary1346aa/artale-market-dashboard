"""Storage package for Artale Market Tracker.

Exports database connection management, schemas, transactions,
and candlestick aggregation services.
"""

from storage.aggregator import KlineAggregator
from storage.database import (
    fetch_active_listings,
    fetch_candles,
    fetch_distinct_items,
    fetch_latest_ask,
    fetch_recent_trades,
    get_connection,
    init_db,
    save_active_listings,
    save_kline_candles,
    save_matched_trades,
)

__all__ = [
    "KlineAggregator",
    "get_connection",
    "init_db",
    "save_active_listings",
    "save_matched_trades",
    "save_kline_candles",
    "fetch_distinct_items",
    "fetch_recent_trades",
    "fetch_active_listings",
    "fetch_candles",
    "fetch_latest_ask",
]
