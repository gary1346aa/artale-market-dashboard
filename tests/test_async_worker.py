"""Unit tests for asynchronous OCR background worker."""

import unittest
from PIL import Image

from pipeline.async_worker import AsyncOcrWorker


class TestAsyncWorker(unittest.TestCase):
    """Tests for AsyncOcrWorker queueing and shutdown."""

    def test_worker_lifecycle(self):
        """Verify worker starts, accepts submit, and shuts down cleanly."""
        worker = AsyncOcrWorker()
        self.assertTrue(worker._thread.is_alive())

        # Submit a dummy frame
        blank = Image.new("RGB", (100, 100), (0, 0, 0))
        worker.submit(blank, tab="query", page_num=1, item_name="測試道具")

        # Shutdown worker and ensure thread exits
        worker.shutdown()
        worker._thread.join(timeout=2.0)
        self.assertFalse(worker._thread.is_alive())


if __name__ == "__main__":
    unittest.main()
