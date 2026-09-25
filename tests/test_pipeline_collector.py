"""Unit tests for market collector state machine and stateless quota checks."""

import unittest
from unittest.mock import MagicMock, patch
from PIL import Image

from pipeline.collector import read_quota_from_frame


class TestPipelineCollector(unittest.TestCase):
    """Tests for collector helper functions and quota evaluation."""

    def test_read_quota_from_blank_frame(self):
        """Verify read_quota_from_frame safely returns None when frame is blank."""
        frame = Image.new("RGB", (1280, 720), (0, 0, 0))
        quota = read_quota_from_frame(frame)
        self.assertIsNone(quota)

    @patch("pipeline.collector.parse_quota_header")
    def test_read_quota_delegates_to_digit_engine(self, mock_parse_quota):
        """Verify read_quota_from_frame crops the header region and calls digit engine."""
        mock_parse_quota.return_value = (450, 500)
        frame = Image.new("RGB", (1280, 720), (50, 50, 50))
        quota = read_quota_from_frame(frame)
        self.assertEqual(quota, 450)
        mock_parse_quota.assert_called_once()

    def test_execute_search_returns_false_when_auction_closed(self):
        """Verify execute_search rejects searches when auction house is closed."""
        from pipeline.collector import MarketCollector
        with patch.object(MarketCollector, "__init__", return_value=None):
            collector = MarketCollector()
            collector.is_auction_open = MagicMock(return_value=False)
            result = collector.execute_search("智慧水晶")
            self.assertFalse(result)

    def test_capture_search_box_crops_correct_coords(self):
        """Verify capture_search_box crops the canonical search box area."""
        from pipeline.collector import MarketCollector
        with patch.object(MarketCollector, "__init__", return_value=None):
            collector = MarketCollector()
            collector.use_adb = False
            collector.capture_frame = MagicMock(
                return_value=Image.new("RGB", (1280, 720), (255, 255, 255))
            )
            crop = collector.capture_search_box()
            self.assertIsNotNone(crop)
            self.assertEqual(crop.size, (450 - 215, 55 - 25))


if __name__ == "__main__":
    unittest.main()
