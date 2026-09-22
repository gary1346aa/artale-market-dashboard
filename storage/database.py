"""SQLite database storage and query transactions for Artale Market Tracker.

Manages connection pooling, WAL journal mode, schemas for active listings,
matched trades, and aggregated OHLCV candles with full transaction safety.
"""

import logging
from pathlib import Path
from contextlib import contextmanager
import sqlite3
from typing import Any, Dict, List, Optional, Union

from config.settings import DATA_DIR, DB_PATH
from core.models import ActiveListing, Candle, MatchedTrade

_logger = logging.getLogger(__name__)


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Creates a thread-safe SQLite connection configured with WAL journal mode.

    Args:
        db_path: Optional custom path to SQLite database.

    Returns:
        sqlite3.Connection object.
    """
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn

@contextmanager
def open_db(db_path: Optional[Path] = None):
    """Context manager for transaction commit and connection close.

    Args:
        db_path: Optional custom path to SQLite database.

    Yields:
        sqlite3.Connection object.
    """
    conn = get_connection(db_path)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db(db_path: Optional[Path] = None) -> None:
    """Initializes SQLite schema and performance indices if not existing.

    Args:
        db_path: Optional custom path to SQLite database.
    """
    with open_db(db_path) as conn:
        cursor = conn.cursor()

        # Table 1: Active sell listings (查詢)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS active_listings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_name TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                total_price INTEGER NOT NULL,
                unit_price INTEGER NOT NULL,
                remaining_time TEXT,
                seller_id TEXT,
                page_number INTEGER,
                captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # Table 2: Matched / Transaction prices (市價)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS matched_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_name TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                matched_unit_price INTEGER NOT NULL,
                total_matched_price INTEGER,
                trade_time TEXT,
                trade_hash TEXT UNIQUE,
                captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # Table 3: Aggregated OHLCV Candlesticks (K-Line)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS kline_candles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_name TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                bucket_time TEXT NOT NULL,
                open_price INTEGER NOT NULL,
                high_price INTEGER NOT NULL,
                low_price INTEGER NOT NULL,
                close_price INTEGER NOT NULL,
                volume INTEGER NOT NULL,
                turnover INTEGER NOT NULL,
                vwap INTEGER NOT NULL,
                lowest_ask INTEGER,
                trade_count INTEGER NOT NULL,
                UNIQUE(item_name, timeframe, bucket_time) ON CONFLICT REPLACE
            )
            """
        )

        # Performance Indexes
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_active_item ON active_listings(item_name, captured_at)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_matched_item ON matched_trades(item_name, captured_at)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_kline_lookup ON kline_candles(item_name, timeframe, bucket_time)"
        )
        conn.commit()


def save_active_listings(
    listings: List[ActiveListing], db_path: Optional[Path] = None
) -> None:
    """Persists a batch of active sell listings into the database.

    Args:
        listings: List of ActiveListing models.
        db_path: Optional custom path to SQLite database.
    """
    if not listings:
        return

    with open_db(db_path) as conn:
        cursor = conn.cursor()
        try:
            cursor.executemany(
                """
                INSERT INTO active_listings (
                    item_name, quantity, total_price, unit_price,
                    remaining_time, seller_id, page_number, captured_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        l.item_name,
                        l.quantity,
                        l.total_price,
                        l.unit_price,
                        l.remaining_time,
                        l.seller_id,
                        l.page_number,
                        l.captured_at.isoformat(),
                    )
                    for l in listings
                ],
            )
            conn.commit()
        except Exception as err:
            _logger.error(f"Failed to insert active_listings batch: {err}")
            raise


def save_matched_trades(
    trades: List[MatchedTrade], db_path: Optional[Path] = None
) -> None:
    """Persists historical transacted trades with deterministic deduplication.

    Args:
        trades: List of MatchedTrade models.
        db_path: Optional custom path to SQLite database.
    """
    if not trades:
        return

    with open_db(db_path) as conn:
        cursor = conn.cursor()
        for idx, t in enumerate(trades):
            # Deterministic hash to deduplicate overlapping pages
            trade_hash = (
                f"{t.item_name.strip()}_{t.quantity}_{t.matched_unit_price}_"
                f"{t.trade_time.strip() if t.trade_time else 'none'}"
            )
            try:
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO matched_trades (
                        item_name, quantity, matched_unit_price,
                        total_matched_price, trade_time, trade_hash, captured_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        t.item_name,
                        t.quantity,
                        t.matched_unit_price,
                        t.total_matched_price,
                        t.trade_time,
                        trade_hash,
                        t.captured_at.isoformat(),
                    ),
                )
            except Exception as err:
                _logger.error(
                    f"Failed to insert matched_trade row {idx} ({t.item_name}): {err}"
                )
                raise
        conn.commit()


def save_kline_candles(
    candles: List[Union[Candle, Dict[str, Any]]],
    db_path: Optional[Path] = None,
) -> None:
    """Upserts aggregated OHLCV candlestick records into kline_candles.

    Args:
        candles: List of Candle models or equivalent dictionaries.
        db_path: Optional custom path to SQLite database.
    """
    if not candles:
        return

    records = []
    for c in candles:
        if isinstance(c, Candle):
            records.append((
                c.item_name,
                c.timeframe,
                c.bucket_time,
                c.open_price,
                c.high_price,
                c.low_price,
                c.close_price,
                c.volume,
                c.turnover,
                c.vwap,
                c.lowest_ask,
                c.trade_count,
            ))
        else:
            records.append((
                c["item_name"],
                c["timeframe"],
                c["bucket_time"],
                c["open_price"],
                c["high_price"],
                c["low_price"],
                c["close_price"],
                c["volume"],
                c["turnover"],
                c["vwap"],
                c.get("lowest_ask"),
                c["trade_count"],
            ))

    with open_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.executemany(
            """
            INSERT INTO kline_candles (
                item_name, timeframe, bucket_time, open_price, high_price,
                low_price, close_price, volume, turnover, vwap, lowest_ask, trade_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            records,
        )
        conn.commit()


def fetch_distinct_items(db_path: Optional[Path] = None) -> List[str]:
    """Retrieves sorted list of all unique item names recorded in the database.

    Args:
        db_path: Optional custom path to SQLite database.

    Returns:
        Alphabetically sorted list of distinct item names.
    """
    with open_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT DISTINCT item_name FROM matched_trades
            UNION
            SELECT DISTINCT item_name FROM active_listings
            ORDER BY 1 ASC
            """
        )
        return [row[0] for row in cursor.fetchall() if row[0]]


def fetch_recent_trades(
    item_name: str, limit: int = 50, db_path: Optional[Path] = None
) -> List[Dict[str, Any]]:
    """Retrieves most recent transacted trades for an item.

    Args:
        item_name: Canonical item name.
        limit: Maximum records to return.
        db_path: Optional custom path to SQLite database.

    Returns:
        List of dicts representing matched trades ordered descending by time.
    """
    with open_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT item_name, quantity, matched_unit_price, total_matched_price,
                   trade_time, captured_at
            FROM matched_trades
            WHERE item_name = ?
            ORDER BY trade_time DESC, captured_at DESC
            LIMIT ?
            """,
            (item_name, limit),
        )
        cols = [
            "item_name",
            "quantity",
            "matched_unit_price",
            "total_matched_price",
            "trade_time",
            "captured_at",
        ]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]


def fetch_active_listings(
    item_name: str, limit: int = 50, db_path: Optional[Path] = None
) -> List[Dict[str, Any]]:
    """Retrieves latest active sell listings for an item.

    Args:
        item_name: Canonical item name.
        limit: Maximum records to return.
        db_path: Optional custom path to SQLite database.

    Returns:
        List of dicts representing active listings.
    """
    with open_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT item_name, quantity, total_price, unit_price,
                   remaining_time, seller_id, page_number, captured_at
            FROM active_listings
            WHERE item_name = ?
            ORDER BY captured_at DESC, unit_price ASC
            LIMIT ?
            """,
            (item_name, limit),
        )
        cols = [
            "item_name",
            "quantity",
            "total_price",
            "unit_price",
            "remaining_time",
            "seller_id",
            "page_number",
            "captured_at",
        ]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]


def fetch_candles(
    item_name: str,
    timeframe: str = "1h",
    limit: int = 100,
    db_path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Retrieves aggregated OHLCV candles for an item.

    Args:
        item_name: Canonical item name.
        timeframe: '1h', '4h', or '1d'.
        limit: Maximum candle bars to return.
        db_path: Optional custom path to SQLite database.

    Returns:
        List of candle dicts ordered ascending by bucket_time.
    """
    with open_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT item_name, timeframe, bucket_time, open_price, high_price,
                   low_price, close_price, volume, turnover, vwap, lowest_ask, trade_count
            FROM kline_candles
            WHERE item_name = ? AND timeframe = ?
            ORDER BY bucket_time ASC
            LIMIT ?
            """,
            (item_name, timeframe, limit),
        )
        cols = [
            "item_name",
            "timeframe",
            "bucket_time",
            "open_price",
            "high_price",
            "low_price",
            "close_price",
            "volume",
            "turnover",
            "vwap",
            "lowest_ask",
            "trade_count",
        ]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]


def fetch_latest_ask(
    item_name: str, db_path: Optional[Path] = None
) -> Optional[int]:
    """Retrieves lowest active ask price for an item within recent snapshot window.

    Args:
        item_name: Canonical item name.
        db_path: Optional custom path to SQLite database.

    Returns:
        Lowest unit price in mesos or None if no active listings found.
    """
    with open_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT min(unit_price) FROM active_listings
            WHERE item_name = ? AND unit_price >= 500
              AND replace(captured_at, 'T', ' ') >= (
                  SELECT datetime(replace(max(captured_at), 'T', ' '), '-30 minutes')
                  FROM active_listings WHERE item_name = ?
              )
            """,
            (item_name, item_name),
        )
        row = cursor.fetchone()
        return row[0] if row and row[0] else None
