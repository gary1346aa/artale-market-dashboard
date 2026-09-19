"""Unit tests for Windows OCR text parsing, cleanup, and typo normalization."""

import unittest
from PIL import Image

from recognition.text_ocr import (
    extract_number,
    get_canonical_watchlist,
    normalize_item_name,
    preprocess_for_ocr,
)


class TestTextOcr(unittest.TestCase):
    """Tests for OCR text extraction and normalization heuristics."""

    def test_extract_number_with_cjk_units(self):
        """Extract numbers from strings containing Chinese currency units (億, 萬)."""
        self.assertEqual(extract_number("85,555 (8萬 5,555)"), 85555)
        self.assertEqual(extract_number("4 , 395 , 000"), 4395000)
        self.assertEqual(extract_number("1,112,111,111 (11億)"), 1112111111)
        self.assertEqual(extract_number("350000"), 350000)
        self.assertIsNone(extract_number(""))
        self.assertIsNone(extract_number("無價格"))

    def test_normalize_item_name_typo_correction(self):
        """Correct common OCR character recognition mistakes using canonical dictionary."""
        self.assertEqual(normalize_item_name("結加特器"), "凍結加持器")
        self.assertEqual(normalize_item_name("碎片"), "時間碎片")
        self.assertEqual(normalize_item_name("力量永品"), "力量水晶")
        self.assertEqual(normalize_item_name("慧水品"), "智慧水晶")

    def test_preprocess_for_ocr_contrast(self):
        """Verify image preprocessing produces an enhanced grayscale PIL image."""
        img = Image.new("RGB", (100, 30), (50, 50, 50))
        processed = preprocess_for_ocr(img)
        self.assertEqual(processed.size, (250, 75))
        self.assertEqual(processed.mode, "L")


if __name__ == "__main__":
    unittest.main()
