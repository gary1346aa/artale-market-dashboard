import sqlite3
from pathlib import Path
from typing import List
from .models import ActiveListing, MatchedTrade

DB_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DB_DIR / "market.db"

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn

def init_db():
    DB_DIR.mkdir(parents=True, exist_ok=True)
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Table 1: Active sell listings (查詢)
        cursor.execute("""
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
        """)
        
        # Table 2: Matched / Transaction prices (市價)
        cursor.execute("""
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
        """)

        # Table 3: Aggregated OHLCV Candlesticks (K-Line)
        cursor.execute("""
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
        """)
        
        # Indexes for fast lookup and trend analysis
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_active_item ON active_listings(item_name, captured_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_matched_item ON matched_trades(item_name, captured_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_kline_lookup ON kline_candles(item_name, timeframe, bucket_time)")
        conn.commit()

def save_active_listings(listings: List[ActiveListing]):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.executemany("""
            INSERT INTO active_listings (item_name, quantity, total_price, unit_price, remaining_time, seller_id, page_number, captured_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            (
                l.item_name,
                l.quantity,
                l.total_price,
                l.unit_price,
                l.remaining_time,
                l.seller_id,
                l.page_number,
                l.captured_at.isoformat()
            ) for l in listings
        ])
        conn.commit()

def save_matched_trades(trades: List[MatchedTrade]):
    with get_connection() as conn:
        cursor = conn.cursor()
        for t in trades:
            # Deterministic hash to deduplicate overlapping pages
            trade_hash = f"{t.item_name.strip()}_{t.quantity}_{t.matched_unit_price}_{t.trade_time.strip()}"
            cursor.execute("""
                INSERT OR IGNORE INTO matched_trades (item_name, quantity, matched_unit_price, total_matched_price, trade_time, trade_hash, captured_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                t.item_name,
                t.quantity,
                t.matched_unit_price,
                t.total_matched_price,
                t.trade_time,
                trade_hash,
                t.captured_at.isoformat()
            ))
        conn.commit()

def save_kline_candles(candles: List[dict]):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.executemany("""
            INSERT INTO kline_candles (
                item_name, timeframe, bucket_time, open_price, high_price, 
                low_price, close_price, volume, turnover, vwap, lowest_ask, trade_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            (
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
                c["trade_count"]
            ) for c in candles
        ])
        conn.commit()

