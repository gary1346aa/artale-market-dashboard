"""Unit tests for dashboard data export and HTML generation."""

import tempfile
import unittest
from pathlib import Path

from storage.database import init_db
from visualization.dashboard_exporter import export_dashboard_data


class TestDashboardExporter(unittest.TestCase):
    """Tests for dashboard payload generation."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_dash.db"
        init_db(db_path=self.db_path)

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_export_dashboard_data_empty_db(self):
        """Export dashboard data structure from empty DB without crashing."""
        data = export_dashboard_data(db_path=self.db_path)
        self.assertIn("items", data)
        self.assertIn("summary", data)
        self.assertIn("data", data)

    def test_export_dashboard_data_24h_window(self):
        """Verify rolling 24h volume only includes candles within 24h of global market time."""
        import json
        import sqlite3

        wl_file = Path(self.temp_dir.name) / "test_wl.json"
        wl_file.write_text(json.dumps(["ItemA", "ItemB"]), encoding="utf-8")

        with sqlite3.connect(self.db_path) as conn:
            c = conn.cursor()
            # Item A: active item with candles within 24h and older than 24h
            # Item B: stale item with trades only 3 days ago
            candles = [
                # item, tf, bucket_time, open, high, low, close, vol, turnover, vwap, trades
                # Global latest is 2026-09-22 12:00:00
                ("ItemA", "1h", "2026-09-20 10:00:00", 100, 110, 95, 105, 50, 5250, 105.0, 5),  # > 24h ago
                ("ItemA", "1h", "2026-09-21 13:00:00", 105, 115, 100, 110, 20, 2200, 110.0, 2), # 23h ago (in window)
                ("ItemA", "1h", "2026-09-22 12:00:00", 110, 120, 108, 115, 30, 3450, 115.0, 3), # 0h ago (in window)
                # Item B: stale item
                ("ItemB", "1h", "2026-09-18 08:00:00", 500, 520, 490, 510, 100, 51000, 510.0, 10),
            ]
            c.executemany(
                """
                INSERT INTO kline_candles (
                    item_name, timeframe, bucket_time, open_price, high_price,
                    low_price, close_price, volume, turnover, vwap, trade_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                candles,
            )

        data = export_dashboard_data(db_path=self.db_path, watchlist_path=wl_file)
        summary_by_item = {s["name"]: s for s in data["summary"]}

        # Item A: only 20 + 30 = 50 volume within 24h window (excludes 50 from Sept 20)
        self.assertIn("ItemA", summary_by_item)
        item_a = summary_by_item["ItemA"]
        self.assertEqual(item_a["vol_24"], 50)
        self.assertEqual(item_a["trades_24"], 5)
        self.assertEqual(item_a["turnover_24"], 5650)
        self.assertEqual(item_a["latest_price"], 115)
        self.assertEqual(item_a["high_24"], 120)
        self.assertEqual(item_a["low_24"], 100)

        # Item B: stale item has 0 volume in the last 24h
        self.assertIn("ItemB", summary_by_item)
        item_b = summary_by_item["ItemB"]
        self.assertEqual(item_b["vol_24"], 0)
        self.assertEqual(item_b["trades_24"], 0)
        self.assertEqual(item_b["turnover_24"], 0)
        self.assertEqual(item_b["latest_price"], 510)
        self.assertEqual(item_b["high_24"], 510)
        self.assertEqual(item_b["low_24"], 510)
        self.assertEqual(item_b["chg_24"], 0.0)


if __name__ == "__main__":
    unittest.main()
