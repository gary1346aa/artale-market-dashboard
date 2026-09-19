"""Unit tests for deterministic digit engine matching."""

import unittest
from PIL import Image

from recognition.digit_engine import (
    match_glyph,
    parse_price_cell,
    parse_quota_header,
    parse_timestamp_cell,
)


class TestDigitEngine(unittest.TestCase):
    """Tests for bitmask digit recognition and quota header detection."""

    def test_parse_quota_header_empty_image(self):
        """Verify parse_quota_header handles blank images safely without crashing."""
        blank_img = Image.new("RGB", (200, 30), (0, 0, 0))
        quota = parse_quota_header(blank_img)
        self.assertIsNone(quota)

    def test_parse_price_cell_blank_image(self):
        """Verify parse_price_cell on uniform image returns None."""
        blank_img = Image.new("RGB", (120, 25), (40, 40, 40))
        res = parse_price_cell(blank_img)
        self.assertIsNone(res)

    def test_match_glyph_thin(self):
        """Verify match_glyph returns '1' for narrow single-pixel column glyphs."""
        thin_img = Image.new("1", (2, 10), 0)
        res = match_glyph(thin_img)
        self.assertEqual(res, "1")


if __name__ == "__main__":
    unittest.main()
