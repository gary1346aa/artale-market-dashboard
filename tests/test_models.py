"""Unit tests for core models (ActiveListing, Candle, MatchedTrade, WatchlistItem)."""

import unittest
from datetime import datetime

from core.models import ActiveListing, Candle, MatchedTrade, WatchlistItem


class TestCoreModels(unittest.TestCase):
    """Tests for typed domain models and Pydantic validation."""

    def test_active_listing_valid_instantiation(self):
        """Instantiate ActiveListing and verify typed field conversions."""
        listing = ActiveListing(
            item_name="力量水晶",
            quantity=10,
            total_price=29400000,
            unit_price=2940000,
            remaining_time="23小時",
            seller_id="Player1",
            page_number=1,
        )
        self.assertEqual(listing.item_name, "力量水晶")
        self.assertEqual(listing.quantity, 10)
        self.assertEqual(listing.total_price, 29400000)
        self.assertEqual(listing.unit_price, 2940000)
        self.assertEqual(listing.remaining_time, "23小時")
        self.assertEqual(listing.seller_id, "Player1")
        self.assertEqual(listing.page_number, 1)
        self.assertIsInstance(listing.captured_at, datetime)

    def test_candle_model_instantiation(self):
        """Instantiate Candle model and verify OHLCV pricing and volume fields."""
        candle = Candle(
            item_name="時間碎片",
            timeframe="1h",
            bucket_time="2026-09-19 12:00:00",
            open_price=350000,
            high_price=380000,
            low_price=340000,
            close_price=375000,
            volume=1420,
            turnover=511200000,
            vwap=360000,
            trade_count=18,
        )
        self.assertEqual(candle.item_name, "時間碎片")
        self.assertEqual(candle.timeframe, "1h")
        self.assertEqual(candle.bucket_time, "2026-09-19 12:00:00")
        self.assertEqual(candle.open_price, 350000)
        self.assertEqual(candle.high_price, 380000)
        self.assertEqual(candle.low_price, 340000)
        self.assertEqual(candle.close_price, 375000)
        self.assertEqual(candle.volume, 1420)
        self.assertEqual(candle.turnover, 511200000)
        self.assertEqual(candle.vwap, 360000)
        self.assertEqual(candle.trade_count, 18)

    def test_matched_trade_model_instantiation(self):
        """Instantiate MatchedTrade and verify trade execution attributes."""
        trade = MatchedTrade(
            item_name="楓葉祝福 20",
            quantity=1,
            matched_unit_price=638000000,
            total_matched_price=638000000,
            trade_time="2026-09-19 13:45",
        )
        self.assertEqual(trade.item_name, "楓葉祝福 20")
        self.assertEqual(trade.quantity, 1)
        self.assertEqual(trade.matched_unit_price, 638000000)
        self.assertEqual(trade.total_matched_price, 638000000)
        self.assertEqual(trade.trade_time, "2026-09-19 13:45")
        self.assertIsInstance(trade.captured_at, datetime)

    def test_watchlist_item_model(self):
        """Instantiate WatchlistItem and check priority and interval fields."""
        item = WatchlistItem(
            item_name="手套攻擊卷軸60%",
            tier=1,
            last_updated=None,
        )
        self.assertEqual(item.item_name, "手套攻擊卷軸60%")
        self.assertEqual(item.tier, 1)
        self.assertIsNone(item.last_updated)


if __name__ == "__main__":
    unittest.main()
