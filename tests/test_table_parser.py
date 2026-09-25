"""Unit tests for MarketParser table row slicing and coordinate scaling."""

import unittest
from PIL import Image

from recognition.table_parser import MarketParser


class TestTableParser(unittest.TestCase):
    """Tests for table row parser and coordinate transformations."""

    def test_scale_box_at_canonical_resolution(self):
        """Verify scale_box returns unchanged coordinates at canonical 1280x720."""
        img = Image.new("RGB", (1280, 720), (0, 0, 0))
        parser = MarketParser(img)
        scaled = parser._scale_box(100, 200, 300, 400)
        self.assertEqual(scaled, (100, 200, 300, 400))

    def test_scale_box_at_scaled_resolution(self):
        """Verify scale_box scales coordinates linearly for scaled captures."""
        # Half-scale image: 640x360
        img = Image.new("RGB", (640, 360), (0, 0, 0))
        parser = MarketParser(img)
        scaled = parser._scale_box(100, 200, 300, 400)
        self.assertEqual(scaled, (50, 100, 150, 200))

    def test_parse_blank_image_returns_empty_or_zero(self):
        """Verify parser on uniform blank frame safely returns empty list."""
        img = Image.new("RGB", (1280, 720), (30, 30, 30))
        parser = MarketParser(img)
        listings = parser.parse_active_listings()
        self.assertEqual(listings, [])

    def test_expected_item_name_assigned(self):
        """Verify parser uses expected_item_name without skipping rows."""
        img = Image.new("RGB", (1280, 720), (30, 30, 30))
        parser = MarketParser(img, item_name="智慧水晶")
        self.assertEqual(parser.expected_item_name, "智慧水晶")


if __name__ == "__main__":
    unittest.main()
