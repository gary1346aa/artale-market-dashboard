"""Multi-worker parallel collection orchestrator.

Spawns independent worker threads across N LDPlayer emulator instances,
dynamically stealing tasks from a thread-safe FIFO queue with live quota checks.
"""

import logging
import queue
import threading
import time
from typing import Dict, List, Optional

from driver.adb_driver import AdbDriver
from pipeline.collector import (
    INSTANCE_TO_DEVICE,
    MarketCollector,
)

_logger = logging.getLogger(__name__)

DEVICE_TO_INSTANCE: Dict[str, str] = {v: k for k, v in INSTANCE_TO_DEVICE.items()}


class ParallelCollector:
    """Orchestrates multi-instance dynamic work-stealing collection across emulators.

    Attributes:
        use_adb: Whether to use ADB driver.
        devices: List of ADB device IDs to utilize as workers.
    """

    def __init__(
        self,
        max_workers: Optional[int] = None,
        devices: Optional[List[str]] = None,
        use_adb: bool = True,
    ) -> None:
        """Initializes ParallelCollector with worker devices."""
        self.use_adb = use_adb
        if devices:
            self.devices = devices
        elif self.use_adb:
            attached = AdbDriver.list_attached_devices()
            if max_workers:
                self.devices = attached[:max_workers] if attached else []
            else:
                self.devices = (
                    attached if attached else ["emulator-5558", "emulator-5560"]
                )
        else:
            self.devices = ["legacy"]

        _logger.info(
            f"ParallelCollector initialized with {len(self.devices)} worker(s): {self.devices}"
        )

    def run_catalog_scan(
        self,
        keywords: List[str],
        max_pages: int = 2,
        target_tab: str = "both",
        start_index: int = 1,
    ) -> None:
        """Executes parallel multi-instance scan across the task queue.

        Args:
            keywords: List of item names.
            max_pages: Max pages to collect per query.
            target_tab: 'both', 'asks', or 'trades'.
            start_index: 1-based start index.
        """
        items = keywords[start_index - 1 :]
        if not items:
            _logger.info("No items to scan.")
            return

        task_queue: queue.Queue = queue.Queue()
        for idx, item in enumerate(items, start_index):
            task_queue.put((idx, len(keywords), item))

        failed_items: List[str] = []
        failed_lock = threading.Lock()
        progress_lock = threading.Lock()
        completed_count = 0
        total_items = len(items)

        def worker_thread(device_id: str) -> None:
            nonlocal completed_count
            inst_name = DEVICE_TO_INSTANCE.get(device_id, device_id)
            _logger.debug(
                f"[{device_id}] Worker booting for instance '{inst_name}'..."
            )

            collector = MarketCollector(
                instance_name=inst_name,
                use_adb=True,
                allow_instance_rotation=False,
            )
            if collector.adb:
                collector.adb.device_id = device_id

            ready = False
            for attempt in range(1, 4):
                if collector.ensure_focus(max_retries=2):
                    ready = True
                    break
                _logger.warning(
                    f"[{device_id}] Auction House entry attempt {attempt}/3 failed. Retrying..."
                )
                time.sleep(3.0)

            if not ready:
                _logger.error(
                    f"[{device_id}] Could not enter Auction House. Worker aborting."
                )
                return

            # Check initial screen quota on entry
            rem = collector.get_screen_quota()
            if rem is not None and rem < 2:
                _logger.warning(
                    f"[{device_id}] Instance '{inst_name}' initial quota exhausted ({rem} < 2). Retiring worker from pool."
                )
                collector.leave_auction()
                collector.shutdown()
                return

            _logger.debug(
                f"[{device_id}] Ready. Draining task queue dynamically..."
            )
            try:
                while not task_queue.empty():
                    try:
                        idx, total_total, item = task_queue.get_nowait()
                    except queue.Empty:
                        break

                    with progress_lock:
                        completed_count += 1
                        curr_progress = completed_count

                    _logger.info(
                        f"[{device_id}] -> Scanning [{idx}/{total_total}] (Batch: {curr_progress}/{total_items}): '{item}'"
                    )

                    try:
                        ok = collector.run_query_collection(
                            item,
                            max_pages=max_pages,
                            target_tab=target_tab,
                        )
                        if not ok:
                            # Live screen quota exhausted on this worker
                            _logger.warning(
                                f"[{device_id}] Quota exhausted on instance '{inst_name}'. Re-queueing '{item}' and retiring worker."
                            )
                            collector.leave_auction()
                            collector.shutdown()
                            task_queue.put((idx, total_total, item))
                            return
                    except Exception as err:
                        _logger.error(
                            f"[{device_id}] Error processing '{item}': {err}"
                        )
                        with failed_lock:
                            failed_items.append(item)
                    finally:
                        task_queue.task_done()
                    time.sleep(1.2)
            finally:
                _logger.debug(
                    f"[{device_id}] Task queue drained. Safely exiting Auction House..."
                )
                collector.shutdown()

        # Launch workers concurrently
        threads: List[threading.Thread] = []
        for dev in self.devices:
            t = threading.Thread(
                target=worker_thread,
                args=(dev,),
                name=f"Worker-{dev}",
                daemon=True,
            )
            threads.append(t)
            t.start()
            time.sleep(0.5)

        for t in threads:
            t.join()

        _logger.info("Parallel catalog collection completed.")
