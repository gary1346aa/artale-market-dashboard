"""Unit tests for Artale Market Tracker modular packages.

Tests configuration invariants, domain models, item categorization,
bitmask digit engine, database transactions, and financial formatting.
"""

from datetime import datetime
import tempfile
import unittest
from pathlib import Path
from PIL import Image

from config.coordinates import (
    Point,
    Rect,
    POS_PRICE_HEADER,
    POS_QUICK_SEARCH,
    REGION_QUOTA_DIGITS,
)
from config.settings import (
    CANONICAL_HEIGHT,
    CANONICAL_WIDTH,
    RESET_HOUR,
    get_seconds_until_next_8am,
)
from core.categories import (
    CATEGORY_ACCESSORY_SCROLL,
    CATEGORY_CONSUMABLE,
    CATEGORY_MATERIAL,
    CATEGORY_WEAPON_SCROLL,
    classify_item,
    classify_item_type,
    get_scroll_rate,
)
from core.models import ActiveListing, Candle, MatchedTrade, WatchlistItem
from core.watchlist import WatchlistManager
from recognition.digit_engine import match_glyph, parse_price_cell, parse_quota_header
from recognition.glyph_table import EXACT_GLYPHS
from recognition.text_ocr import extract_number, normalize_item_name
from storage.database import (
    fetch_active_listings,
    fetch_distinct_items,
    fetch_recent_trades,
    init_db,
    save_active_listings,
    save_matched_trades,
)
from visualization.theme import (
    calc_nice_ticks,
    format_axis_price,
    format_price_cjk,
    format_vol_cjk,
)


class TestConfigAndCoordinates(unittest.TestCase):
    """Tests configuration and screen coordinate specifications."""

    def test_canonical_canvas_dimensions(self):
        self.assertEqual(CANONICAL_WIDTH, 1280)
        self.assertEqual(CANONICAL_HEIGHT, 720)
        self.assertEqual(RESET_HOUR, 8)

    def test_point_and_rect(self):
        pt = Point(10, 20)
        self.assertEqual(pt.x, 10)
        self.assertEqual(pt.y, 20)

        r = Rect(10, 20, 110, 120)
        self.assertEqual(r.width, 100)
        self.assertEqual(r.height, 100)
        self.assertEqual(r.as_tuple(), (10, 20, 110, 120))

    def test_seconds_until_8am(self):
        sec = get_seconds_until_next_8am()
        self.assertGreaterEqual(sec, 0.0)
        self.assertLessEqual(sec, 86400.0)


class TestCoreDomain(unittest.TestCase):
    """Tests domain models, categorization, and tier logic."""

    def test_active_listing_model(self):
        listing = ActiveListing(
            item_name="力量水晶",
            quantity=10,
            total_price=29400000,
            unit_price=2940000,
            remaining_time="23小時",
            page_number=1,
        )
        self.assertEqual(listing.item_name, "力量水晶")
        self.assertEqual(listing.quantity, 10)
        self.assertEqual(listing.total_price, 29400000)
        self.assertEqual(listing.unit_price, 2940000)

    def test_matched_trade_model(self):
        trade = MatchedTrade(
            item_name="楓葉祝福 20",
            quantity=1,
            matched_unit_price=638000000,
            total_matched_price=638000000,
            trade_time="2026-09-14 16:30",
        )
        self.assertEqual(trade.item_name, "楓葉祝福 20")
        self.assertEqual(trade.matched_unit_price, 638000000)

    def test_item_classification(self):
        self.assertEqual(classify_item("超級藥水"), CATEGORY_CONSUMABLE)
        self.assertEqual(classify_item("墜飾智力卷軸30%"), CATEGORY_ACCESSORY_SCROLL)
        self.assertEqual(classify_item("槍攻擊卷軸60%"), CATEGORY_WEAPON_SCROLL)
        self.assertEqual(classify_item("時間碎片"), CATEGORY_MATERIAL)

    def test_scroll_rate_parsing(self):
        self.assertEqual(get_scroll_rate("手套攻擊卷軸60%"), "60%")
        self.assertEqual(get_scroll_rate("頭盔智力卷軸100%"), "100%")
        self.assertEqual(get_scroll_rate("力量水晶"), "-")

    def test_badge_classification(self):
        self.assertEqual(classify_item_type("墜飾智力卷軸30%"), "飾品卷軸")
        self.assertEqual(classify_item_type("時間碎片"), "鍛造材料")


class TestRecognitionEngine(unittest.TestCase):
    """Tests deterministic digit recognition and OCR normalization."""

    def test_glyph_table_loaded(self):
        self.assertGreater(len(EXACT_GLYPHS), 800)

    def test_extract_number(self):
        self.assertEqual(extract_number("85,555 (8萬 5,555)"), 85555)
        self.assertEqual(extract_number("4 , 395 , 000"), 4395000)
        self.assertEqual(extract_number("1,112,111,111 (11億)"), 1112111111)
        self.assertIsNone(extract_number(""))

    def test_normalize_item_name(self):
        self.assertEqual(normalize_item_name("結加特器"), "凍結加持器")
        self.assertEqual(normalize_item_name("碎片"), "時間碎片")
        self.assertEqual(normalize_item_name("力量永品"), "力量水晶")


class TestStorageAndDatabase(unittest.TestCase):
    """Tests SQLite connection pooling, transactions, and queries."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_market.db"
        init_db(db_path=self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_save_and_fetch_active_listings(self):
        listings = [
            ActiveListing(
                item_name="力量水晶",
                quantity=5,
                total_price=14500000,
                unit_price=2900000,
                remaining_time="20小時",
                page_number=1,
            )
        ]
        save_active_listings(listings, db_path=self.db_path)
        fetched = fetch_active_listings("力量水晶", db_path=self.db_path)
        self.assertEqual(len(fetched), 1)
        self.assertEqual(fetched[0]["item_name"], "力量水晶")
        self.assertEqual(fetched[0]["unit_price"], 2900000)

    def test_save_and_fetch_matched_trades(self):
        trades = [
            MatchedTrade(
                item_name="超級藥水",
                quantity=100,
                matched_unit_price=4500,
                total_matched_price=450000,
                trade_time="2026-09-14 12:00",
            )
        ]
        save_matched_trades(trades, db_path=self.db_path)
        fetched = fetch_recent_trades("超級藥水", db_path=self.db_path)
        self.assertEqual(len(fetched), 1)
        self.assertEqual(fetched[0]["matched_unit_price"], 4500)


class TestVisualizationTheme(unittest.TestCase):
    """Tests financial formatting and tick generation."""

    def test_format_price_cjk(self):
        self.assertEqual(format_price_cjk(638000000), "6.38 億")
        self.assertEqual(format_price_cjk(2800000), "280.0 萬")
        self.assertEqual(format_price_cjk(4500), "4,500")
        self.assertEqual(format_price_cjk(None), "-")

    def test_format_axis_price(self):
        self.assertEqual(format_axis_price(3000000, is_badge=False), "300 萬")
        self.assertEqual(format_axis_price(2767000, is_badge=True), "276.7 萬")
        self.assertEqual(format_axis_price(450000000, is_badge=False), "4.5 億")

    def test_format_vol_cjk(self):
        self.assertEqual(format_vol_cjk(1250), "1,250 件")
        self.assertEqual(format_vol_cjk(0), "0 件")

    def test_calc_nice_ticks(self):
        ticks, n_min, n_max = calc_nice_ticks(2000000, 3000000, target_ticks=5)
        self.assertGreaterEqual(len(ticks), 3)
        self.assertLessEqual(n_min, 2000000)
        self.assertGreaterEqual(n_max, 3000000)


if __name__ == "__main__":
    unittest.main()
