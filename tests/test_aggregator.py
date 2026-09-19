"""Unit tests for candlestick OHLCV aggregation engine."""

import gc
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from core.models import MatchedTrade
from storage.aggregator import KlineAggregator
from storage.database import init_db, save_matched_trades


class TestAggregator(unittest.TestCase):
    """Tests for trade bucketing and OHLCV candle computation."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_agg.db"
        init_db(db_path=self.db_path)
        self.aggregator = KlineAggregator(db_path=self.db_path)

    def tearDown(self):
        del self.aggregator
        gc.collect()
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_parse_trade_datetime_various_formats(self):
        """Parse different date string formats into standard datetime."""
        dt1 = self.aggregator.parse_trade_datetime("2026-09-19 14:30")
        self.assertEqual(dt1.year, 2026)
        self.assertEqual(dt1.minute, 30)

        dt2 = self.aggregator.parse_trade_datetime("2026-09-19 14:30:15")
        self.assertEqual(dt2.second, 15)

    def test_get_bucket_timestamp(self):
        """Verify time bucketing for 1h, 4h, and 1d intervals."""
        dt = datetime(2026, 9, 19, 14, 35, 20)

        # 1h bucket -> 14:00:00
        b_1h = self.aggregator.get_bucket_timestamp(dt, "1h")
        self.assertEqual(b_1h, "2026-09-19 14:00:00")

        # 4h bucket -> 12:00:00 (since 14 // 4 * 4 = 12)
        b_4h = self.aggregator.get_bucket_timestamp(dt, "4h")
        self.assertEqual(b_4h, "2026-09-19 12:00:00")

        # 1d bucket -> 00:00:00
        b_1d = self.aggregator.get_bucket_timestamp(dt, "1d")
        self.assertEqual(b_1d, "2026-09-19 00:00:00")

    def test_aggregate_item_candles_ohlcv_accuracy(self):
        """Aggregate raw trades into 1h candle and verify Open, High, Low, Close, Volume."""
        # Realistic prices >= 500:
        # Trade 1 at 14:05: price 10000, qty 5
        # Trade 2 at 14:15: price 12000, qty 3
        # Trade 3 at 14:25: price 9000,  qty 2
        # Trade 4 at 14:45: price 11000, qty 10
        trades = [
            MatchedTrade(item_name="力量水晶", quantity=5, matched_unit_price=10000, total_matched_price=50000, trade_time="2026-09-19 14:05"),
            MatchedTrade(item_name="力量水晶", quantity=3, matched_unit_price=12000, total_matched_price=36000, trade_time="2026-09-19 14:15"),
            MatchedTrade(item_name="力量水晶", quantity=2, matched_unit_price=9000, total_matched_price=18000, trade_time="2026-09-19 14:25"),
            MatchedTrade(item_name="力量水晶", quantity=10, matched_unit_price=11000, total_matched_price=110000, trade_time="2026-09-19 14:45"),
        ]
        save_matched_trades(trades, db_path=self.db_path)

        candles = self.aggregator.aggregate_item("力量水晶", timeframe="1h")
        self.assertEqual(len(candles), 1)
        c = candles[0]
        self.assertEqual(c.bucket_time, "2026-09-19 14:00:00")
        self.assertEqual(c.open_price, 10000)
        self.assertEqual(c.high_price, 12000)
        self.assertEqual(c.low_price, 9000)
        self.assertEqual(c.close_price, 11000)
        self.assertEqual(c.volume, 20)  # 5 + 3 + 2 + 10
        self.assertEqual(c.trade_count, 4)


if __name__ == "__main__":
    unittest.main()
