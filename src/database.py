import sqlite3
from pathlib import Path
from typing import List
from .models import ActiveListing, MatchedTrade

DB_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DB_DIR / "market.db"

def init_db():
    DB_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
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
                captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Indexes for fast lookup and trend analysis
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_active_item ON active_listings(item_name, captured_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_matched_item ON matched_trades(item_name, captured_at)")
        conn.commit()

def save_active_listings(listings: List[ActiveListing]):
    with sqlite3.connect(DB_PATH) as conn:
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
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.executemany("""
            INSERT INTO matched_trades (item_name, quantity, matched_unit_price, total_matched_price, trade_time, captured_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, [
            (
                t.item_name,
                t.quantity,
                t.matched_unit_price,
                t.total_matched_price,
                t.trade_time,
                t.captured_at.isoformat()
            ) for t in trades
        ])
        conn.commit()
