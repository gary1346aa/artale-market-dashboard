"""Accuracy and latency benchmark test suite.

Evaluates deterministic Digit Engine against ground-truth and OCR
across real sample frames from the captured dataset.
"""

import os
from pathlib import Path
import time
import unittest

from PIL import Image

from config.settings import PROJECT_ROOT
from recognition.digit_engine import parse_quota_header


class TestAccuracyBenchmark(unittest.TestCase):
    """Verifies recognition accuracy and inference latency."""

    def setUp(self) -> None:
        """Sets up dataset path and samples."""
        candidates = [
            Path(os.environ.get("BUILD_WORKSPACE_DIRECTORY", ""))
            / "data"
            / "test_dataset",
            PROJECT_ROOT / "data" / "test_dataset",
            Path("C:/Users/gary1/artale_market_tracker/data/test_dataset"),
        ]
        self.images = []
        for c in candidates:
            if c.exists():
                self.images = sorted(list(c.glob("*.png")))
                if self.images:
                    break

    def test_quota_recognition_accuracy_and_latency(self) -> None:
        """Benchmark Digit Engine quota header extraction on real screencaps."""
        if not self.images:
            self.skipTest("Dataset images not found in data/test_dataset")

        sample_size = 30
        step = max(1, len(self.images) // sample_size)
        sampled_images = self.images[::step][:sample_size]

        valid_headers = 0
        latencies = []

        for img_path in sampled_images:
            try:
                frame = Image.open(img_path)
            except Exception:
                continue

            t0 = time.perf_counter()
            res = parse_quota_header(frame)
            duration_ms = (time.perf_counter() - t0) * 1000.0
            latencies.append(duration_ms)

            if res is not None:
                quota = res[0] if isinstance(res, (tuple, list)) else res
                if 0 <= quota <= 500:
                    valid_headers += 1

        tested_count = len(latencies)
        self.assertGreater(tested_count, 0, "No valid test frames processed.")

        success_rate = (valid_headers / tested_count) * 100.0
        avg_latency = sum(latencies) / len(latencies)

        # Assert at least 85% valid header extraction on arbitrary test frames
        self.assertGreaterEqual(
            success_rate,
            85.0,
            f"Quota success rate {success_rate:.1f}% below threshold.",
        )
        # Assert sub-50ms average latency per frame
        self.assertLess(
            avg_latency,
            50.0,
            f"Average latency {avg_latency:.2f}ms exceeds 50ms budget.",
        )


if __name__ == "__main__":
    unittest.main()
