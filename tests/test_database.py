"""Unit tests for SQLite database transactions, schemas, and queries."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.models import ActiveListing, Candle, MatchedTrade
from storage.database import (
    fetch_active_listings,
    fetch_candles,
    fetch_distinct_items,
    fetch_latest_ask,
    fetch_recent_trades,
    get_connection,
    init_db,
    open_db,
    save_active_listings,
    save_kline_candles,
    save_matched_trades,
)


class TestStorageDatabase(unittest.TestCase):
    """Tests for SQLite database operations and context manager."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_market.db"
        init_db(db_path=self.db_path)

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_init_db_creates_tables_and_indices(self):
        """Verify schema tables and indices are initialized properly."""
        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = {row[0] for row in cursor.fetchall()}
            self.assertIn("active_listings", tables)
            self.assertIn("matched_trades", tables)
            self.assertIn("kline_candles", tables)

    def test_open_db_context_commit(self):
        """Verify open_db context manager automatically commits transaction."""
        with open_db(self.db_path) as conn:
            conn.execute(
                "INSERT INTO active_listings (item_name, quantity, total_price, unit_price) VALUES (?, ?, ?, ?)",
                ("力量水晶", 1, 3000000, 3000000),
            )

        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM active_listings WHERE item_name = '力量水晶'")
            self.assertEqual(cursor.fetchone()[0], 1)

    def test_open_db_context_rollback_on_error(self):
        """Verify open_db context manager rolls back changes upon unhandled exception."""
        try:
            with open_db(self.db_path) as conn:
                conn.execute(
                    "INSERT INTO active_listings (item_name, quantity, total_price, unit_price) VALUES (?, ?, ?, ?)",
                    ("超級藥水", 10, 45000, 4500),
                )
                raise RuntimeError("Simulated failure")
        except RuntimeError:
            pass

        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM active_listings WHERE item_name = '超級藥水'")
            self.assertEqual(cursor.fetchone()[0], 0)

    def test_save_and_fetch_active_listings(self):
        """Insert and query active order book listings."""
        listings = [
            ActiveListing(
                item_name="力量水晶",
                quantity=5,
                total_price=14500000,
                unit_price=2900000,
                remaining_time="20小時",
                page_number=1,
            ),
            ActiveListing(
                item_name="力量水晶",
                quantity=10,
                total_price=30000000,
                unit_price=3000000,
                remaining_time="22小時",
                page_number=1,
            ),
        ]
        save_active_listings(listings, db_path=self.db_path)
        fetched = fetch_active_listings("力量水晶", db_path=self.db_path)
        self.assertEqual(len(fetched), 2)
        prices = [r["unit_price"] for r in fetched]
        self.assertIn(2900000, prices)
        self.assertIn(3000000, prices)

    def test_save_and_fetch_matched_trades(self):
        """Insert and query matched trade execution records."""
        trades = [
            MatchedTrade(
                item_name="楓葉祝福 20",
                quantity=1,
                matched_unit_price=638000000,
                total_matched_price=638000000,
                trade_time="2026-09-19 10:00",
            )
        ]
        save_matched_trades(trades, db_path=self.db_path)
        fetched = fetch_recent_trades("楓葉祝福 20", db_path=self.db_path)
        self.assertEqual(len(fetched), 1)
        self.assertEqual(fetched[0]["matched_unit_price"], 638000000)

    def test_save_and_fetch_kline_candles(self):
        """Save aggregated OHLCV candles and retrieve by timeframe."""
        candles = [
            Candle(
                item_name="時間碎片",
                timeframe="1h",
                bucket_time="2026-09-19 10:00:00",
                open_price=340000,
                high_price=360000,
                low_price=335000,
                close_price=355000,
                volume=850,
                turnover=300000000,
                vwap=350000,
                trade_count=12,
            )
        ]
        save_kline_candles(candles, db_path=self.db_path)
        fetched = fetch_candles("時間碎片", timeframe="1h", db_path=self.db_path)
        self.assertEqual(len(fetched), 1)
        self.assertEqual(fetched[0]["close_price"], 355000)

    def test_fetch_latest_ask(self):
        """Calculate lowest current active ask price for an item."""
        listings = [
            ActiveListing(
                item_name="力量水晶",
                quantity=1,
                total_price=2900000,
                unit_price=2900000,
                page_number=1,
            ),
            ActiveListing(
                item_name="力量水晶",
                quantity=2,
                total_price=6200000,
                unit_price=3100000,
                page_number=1,
            ),
        ]
        save_active_listings(listings, db_path=self.db_path)
        latest_ask = fetch_latest_ask("力量水晶", db_path=self.db_path)
        self.assertEqual(latest_ask, 2900000)

    def test_fetch_distinct_items(self):
        """Retrieve distinct item names across listings and trades."""
        save_active_listings(
            [ActiveListing(item_name="物品A", quantity=1, total_price=100, unit_price=100, page_number=1)],
            db_path=self.db_path,
        )
        save_matched_trades(
            [MatchedTrade(item_name="物品B", quantity=1, matched_unit_price=200, total_matched_price=200, trade_time="2026-09-19 12:00")],
            db_path=self.db_path,
        )
        items = fetch_distinct_items(db_path=self.db_path)
        self.assertIn("物品A", items)
        self.assertIn("物品B", items)


if __name__ == "__main__":
    unittest.main()
