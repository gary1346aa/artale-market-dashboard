"""Data models and schemas for Artale Market Tracker.

Defines Pydantic models for order book listings, completed trade records,
aggregated financial candles, and watchlist entries with full type safety.
"""

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


def _current_utc_time() -> datetime:
    """Returns current UTC datetime with timezone awareness."""
    return datetime.now(timezone.utc)


class ActiveListing(BaseModel):
    """Represents an active sell listing from the 查詢 (Query / Listings) tab.

    Attributes:
        item_name: Normalized name of the item.
        quantity: Item bundle quantity listed for sale (default: 1).
        total_price: Total listing price in mesos.
        unit_price: Price per individual unit in mesos.
        remaining_time: Textual duration remaining (e.g. '23小時59分').
        seller_id: In-game name of the selling character, if visible.
        page_number: Table page index where this listing was captured.
        captured_at: Datetime when the screenshot was parsed.
    """
    item_name: str
    quantity: int = 1
    total_price: int
    unit_price: int
    remaining_time: Optional[str] = None
    seller_id: Optional[str] = None
    page_number: Optional[int] = None
    captured_at: datetime = Field(default_factory=_current_utc_time)


class MatchedTrade(BaseModel):
    """Represents a historical completed transaction from the 市價 tab.

    Attributes:
        item_name: Normalized name of the item.
        quantity: Transacted item quantity (default: 1).
        matched_unit_price: Price per individual unit transacted in mesos.
        total_matched_price: Total transaction value in mesos.
        trade_time: Transaction timestamp string in 'YYYY-MM-DD HH:MM' format.
        trade_hash: Deterministic deduplication hash.
        captured_at: Datetime when the screenshot was parsed.
    """
    item_name: str
    quantity: int = 1
    matched_unit_price: int
    total_matched_price: Optional[int] = None
    trade_time: Optional[str] = None
    trade_hash: Optional[str] = None
    captured_at: datetime = Field(default_factory=_current_utc_time)


class Candle(BaseModel):
    """Represents an aggregated OHLCV candlestick bar.

    Attributes:
        item_name: Normalized name of the item.
        timeframe: Candle interval timeframe ('1h', '4h', or '1d').
        bucket_time: Interval start timestamp in 'YYYY-MM-DD HH:MM:SS' format.
        open_price: Opening unit price in mesos.
        high_price: Highest unit price in mesos during this interval.
        low_price: Lowest unit price in mesos during this interval.
        close_price: Closing unit price in mesos.
        volume: Total units transacted during this interval.
        turnover: Total meso turnover during this interval.
        vwap: Volume-Weighted Average Price in mesos.
        lowest_ask: Lowest active sell listing unit price at candle close.
        trade_count: Number of distinct trade executions within the interval.
    """
    item_name: str
    timeframe: str
    bucket_time: str
    open_price: int
    high_price: int
    low_price: int
    close_price: int
    volume: int
    turnover: int
    vwap: int
    lowest_ask: Optional[int] = None
    trade_count: int = 0


class WatchlistItem(BaseModel):
    """Represents a watchlist catalog entry with priority tier and update state.

    Attributes:
        item_name: Canonical in-game item name.
        tier: Monitoring priority tier (1: 20m, 2: 4h, 3: 12h, 4: 24h).
        last_updated: ISO or formatted timestamp string of the last scan.
    """
    item_name: str
    tier: int = 3
    last_updated: Optional[str] = None
