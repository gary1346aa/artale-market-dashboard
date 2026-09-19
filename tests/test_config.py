"""Unit tests for config package (coordinates and settings)."""

import unittest
from datetime import datetime, timedelta

from config.coordinates import (
    Point,
    Rect,
    POS_CONFIRM_INPUT,
    POS_PRICE_HEADER,
    POS_QUICK_SEARCH,
    POS_SIDEBAR_SEARCH,
    REGION_QUOTA_DIGITS,
    ROW_BOUNDS_1280,
)
from config.settings import (
    CANONICAL_HEIGHT,
    CANONICAL_WIDTH,
    DATA_DIR,
    DB_PATH,
    RESET_HOUR,
    WATCHLIST_PATH,
    get_seconds_until_next_8am,
    setup_logging,
)


class TestConfigSettings(unittest.TestCase):
    """Tests for system settings and reset calculations."""

    def test_canonical_canvas_dimensions(self):
        """Verify canonical 1280x720 canvas dimensions and 8 AM reset hour."""
        self.assertEqual(CANONICAL_WIDTH, 1280)
        self.assertEqual(CANONICAL_HEIGHT, 720)
        self.assertEqual(RESET_HOUR, 8)

    def test_paths_configured(self):
        """Verify default database and watchlist paths are properly defined."""
        self.assertTrue(str(DB_PATH).endswith(".db"))
        self.assertTrue(str(WATCHLIST_PATH).endswith(".json"))
        self.assertIsNotNone(DATA_DIR)

    def test_seconds_until_next_8am_bounds(self):
        """Verify seconds until next 8 AM is strictly within (0, 86400] seconds."""
        seconds = get_seconds_until_next_8am()
        self.assertGreater(seconds, 0)
        self.assertLessEqual(seconds, 86400)

    def test_seconds_until_next_8am_calculation(self):
        """Verify next 8 AM calculation before and after reset hour."""
        # 1. Before 8 AM (e.g. 05:00) -> 3 hours = 10800 seconds
        dt_before = datetime(2026, 9, 19, 5, 0, 0)
        sec_before = get_seconds_until_next_8am(dt_before)
        self.assertEqual(sec_before, 3 * 3600)

        # 2. After 8 AM (e.g. 09:00) -> 23 hours = 82800 seconds
        dt_after = datetime(2026, 9, 19, 9, 0, 0)
        sec_after = get_seconds_until_next_8am(dt_after)
        self.assertEqual(sec_after, 23 * 3600)

        # 3. Exactly at 8 AM (e.g. 08:00:00) -> Next day 8 AM = 86400 seconds
        dt_exact = datetime(2026, 9, 19, 8, 0, 0)
        sec_exact = get_seconds_until_next_8am(dt_exact)
        self.assertEqual(sec_exact, 86400)

    def test_setup_logging(self):
        """Verify logging setup initializes logger with proper level."""
        logger = setup_logging()
        self.assertIsNotNone(logger)
        self.assertTrue(logger.hasHandlers())


class TestConfigCoordinates(unittest.TestCase):
    """Tests for normalized point, rect, and UI landmark coordinates."""

    def test_point_namedtuple(self):
        """Verify Point namedtuple coordinate access."""
        pt = Point(100, 250)
        self.assertEqual(pt.x, 100)
        self.assertEqual(pt.y, 250)

    def test_rect_namedtuple(self):
        """Verify Rect namedtuple geometry calculations (width, height, as_tuple)."""
        r = Rect(100, 200, 300, 450)
        self.assertEqual(r.width, 200)
        self.assertEqual(r.height, 250)
        self.assertEqual(r.as_tuple(), (100, 200, 300, 450))

    def test_ui_landmarks_within_bounds(self):
        """Verify all critical UI points and regions are inside 1280x720 canvas."""
        for name, pt in [
            ("POS_PRICE_HEADER", POS_PRICE_HEADER),
            ("POS_QUICK_SEARCH", POS_QUICK_SEARCH),
            ("POS_CONFIRM_INPUT", POS_CONFIRM_INPUT),
            ("POS_SIDEBAR_SEARCH", POS_SIDEBAR_SEARCH),
        ]:
            self.assertTrue(0 <= pt.x <= 1280, f"{name}.x out of bounds")
            self.assertTrue(0 <= pt.y <= 720, f"{name}.y out of bounds")

        self.assertTrue(
            0 <= REGION_QUOTA_DIGITS.x1 < REGION_QUOTA_DIGITS.x2 <= 1280,
            "REGION_QUOTA_DIGITS x out of bounds",
        )
        self.assertTrue(
            0 <= REGION_QUOTA_DIGITS.y1 < REGION_QUOTA_DIGITS.y2 <= 720,
            "REGION_QUOTA_DIGITS y out of bounds",
        )

    def test_table_row_bounds(self):
        """Verify table row bounds have exactly 7 rows with non-overlapping heights."""
        self.assertEqual(len(ROW_BOUNDS_1280), 7)

        for i in range(len(ROW_BOUNDS_1280) - 1):
            curr_y1, curr_y2 = ROW_BOUNDS_1280[i]
            next_y1, next_y2 = ROW_BOUNDS_1280[i + 1]
            self.assertLessEqual(curr_y2, next_y1)


if __name__ == "__main__":
    unittest.main()
