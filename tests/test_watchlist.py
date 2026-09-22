"""Unit tests for watchlist manager and tier evaluation."""

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from core.watchlist import WatchlistManager


class TestWatchlist(unittest.TestCase):
    """Tests for WatchlistManager tier assignment and due queries."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.watchlist_path = Path(self.temp_dir.name) / "test_watchlist.json"

        # Dict format matching items_watchlist.json schema
        data = {
            "力量水晶": {
                "tier": 1,
                "last_updated": None,
            },
            "時間碎片": {
                "tier": 2,
                "last_updated": (datetime.now() - timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S"),
            },
            "超級藥水": {
                "tier": 3,
                "last_updated": (datetime.now() - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S"),
            },
        }
        with open(self.watchlist_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        self.manager = WatchlistManager(watchlist_path=self.watchlist_path)

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_load_watchlist(self):
        """Load watchlist from JSON and parse into item dictionary."""
        order, data = self.manager.load_raw_watchlist()
        self.assertEqual(len(order), 3)
        self.assertIn("力量水晶", order)
        self.assertIn("時間碎片", order)
        self.assertIn("超級藥水", order)

    def test_due_items_filtering(self):
        """Filter items that are due based on elapsed time since last scan."""
        due_items, min_wait, next_item = self.manager.get_due_items()
        # "力量水晶" (never scanned) -> due
        # "時間碎片" (scanned 5h ago, tier 2 interval is 4h) -> due
        # "超級藥水" (scanned 10m ago, tier 3 interval is 12h) -> not due
        self.assertIn("力量水晶", due_items)
        self.assertIn("時間碎片", due_items)
        self.assertNotIn("超級藥水", due_items)

    def test_classify_tier_boundaries(self):
        """Verify velocity tier assignment based on trade velocity metrics."""
        # Tier 1: peak_hr >= 70 or safe_overflow_hrs <= 2.0
        self.assertEqual(WatchlistManager.classify_tier(peak_hr=75, safe_overflow_hrs=1.8), 1)
        # Tier 2: peak_hr >= 35 or safe_overflow_hrs <= 4.0
        self.assertEqual(WatchlistManager.classify_tier(peak_hr=40, safe_overflow_hrs=3.5), 2)
        # Tier 3: peak_hr >= 18 or safe_overflow_hrs <= 7.8
        self.assertEqual(WatchlistManager.classify_tier(peak_hr=20, safe_overflow_hrs=7.0), 3)
        # Tier 4: peak_hr >= 9 or safe_overflow_hrs <= 15.6
        self.assertEqual(WatchlistManager.classify_tier(peak_hr=12, safe_overflow_hrs=11.6), 4)
        # Tier 5: peak_hr >= 5 or safe_overflow_hrs <= 28.0
        self.assertEqual(WatchlistManager.classify_tier(peak_hr=6, safe_overflow_hrs=23.3), 5)
        # Tier 6: peak_hr < 5
        self.assertEqual(WatchlistManager.classify_tier(peak_hr=2, safe_overflow_hrs=70.0), 6)


if __name__ == "__main__":
    unittest.main()
