import queue
import threading
import time
import logging
from typing import List, Optional
from .collector import MarketCollector, INSTANCE_TO_DEVICE
from .adb_controller import AdbController
from .tier_evaluator import TierEvaluator

logger = logging.getLogger("ParallelCollector")

DEVICE_TO_INSTANCE = {v: k for k, v in INSTANCE_TO_DEVICE.items()}

class ParallelCollector:
    """
    Orchestrates multi-instance dynamic work-stealing collection across N LDPlayer emulators.
    Scales seamlessly to 2, 3, 4, or any number of ADB-connected instances.
    """
    def __init__(self, max_workers: Optional[int] = None, devices: Optional[List[str]] = None, use_adb: bool = True):
        self.use_adb = use_adb
        if devices:
            self.devices = devices
        elif self.use_adb:
            attached = AdbController.list_attached_devices()
            if max_workers:
                self.devices = attached[:max_workers] if attached else []
            else:
                self.devices = attached if attached else ["emulator-5558", "emulator-5560"]
        else:
            self.devices = ["legacy"]

        logger.info(f"ParallelCollector initialized with {len(self.devices)} worker(s): {self.devices}")

    def run_catalog_scan(
        self,
        keywords: List[str],
        max_pages: int = 2,
        target_tab: str = "both",
        start_index: int = 1,
        max_pages_per_query: Optional[int] = None
    ):
        effective_pages = max_pages_per_query if max_pages_per_query is not None else max_pages
        items = keywords[start_index - 1:]
        if not items:
            logger.info("No items to scan.")
            return

        task_queue = queue.Queue()
        for idx, item in enumerate(items, start_index):
            task_queue.put((idx, len(keywords), item))

        failed_items = []
        failed_lock = threading.Lock()
        progress_lock = threading.Lock()
        completed_count = 0
        total_items = len(items)

        def worker_thread(device_id: str):
            nonlocal completed_count
            inst_name = DEVICE_TO_INSTANCE.get(device_id, device_id)
            from .quota_manager import pause_until_next_8am

            logger.info(f"[{device_id}] Worker booting for instance '{inst_name}'...")

            collector = MarketCollector(instance_name=inst_name, use_adb=True, allow_instance_rotation=False)
            collector.adb.device_id = device_id

            ready = False
            for attempt in range(1, 4):
                if collector.ensure_focus(max_retries=2):
                    ready = True
                    break
                logger.warning(f"[{device_id}] Auction House entry attempt {attempt}/3 failed. Checking cooldown and retrying...")
                time.sleep(3.0)

            if not ready:
                logger.error(f"[{device_id}] Could not verify or enter Auction House after 3 attempts. Worker aborting.")
                return

            # Check screen quota on entry
            rem = collector.get_screen_quota()
            if rem is not None and rem < 2:
                logger.warning(f"[{device_id}] Instance '{inst_name}' initial quota exhausted ({rem} < 2). Pausing until 08:00 AM reset...")
                collector.leave_auction()
                pause_until_next_8am(inst_name)
                collector.ensure_focus()

            logger.info(f"[{device_id}] Ready. Draining task queue dynamically...")
            try:
                while not task_queue.empty():
                    try:
                        idx, total_total, item = task_queue.get_nowait()
                    except queue.Empty:
                        break

                    with progress_lock:
                        completed_count += 1
                        curr_progress = completed_count

                    logger.info(f"[{device_id}] -> Scanning [{idx}/{total_total}] (Batch Progress: {curr_progress}/{total_items}): '{item}'")

                    try:
                        ok = collector.run_query_collection(item, max_pages=effective_pages, target_tab=target_tab)
                        if not ok:
                            # Screen quota < 2: re-queue item and pause instance until 08:00 AM
                            logger.warning(f"[{device_id}] Instance '{inst_name}' quota exhausted (< 2). Re-queuing '{item}' and pausing worker until 08:00 AM...")
                            task_queue.put((idx, total_total, item))
                            collector.leave_auction()
                            pause_until_next_8am(inst_name)
                            collector.ensure_focus()
                    except Exception as e:
                        logger.error(f"[{device_id}] Error scanning '{item}': {e}")
                        with failed_lock:
                            failed_items.append(item)
                    finally:
                        task_queue.task_done()
            finally:
                collector.shutdown()
                logger.info(f"[{device_id}] Work queue drained or worker stopped. Exited Auction House.")

        # Spawn worker threads
        threads = []
        for dev in self.devices:
            t = threading.Thread(target=worker_thread, args=(dev,), daemon=True)
            t.start()
            threads.append(t)

        # Wait for all workers to finish
        for t in threads:
            t.join()

        logger.info(f"Parallel catalog scan completed across {len(self.devices)} workers.")

        # Autonomous Retry Pass if any items failed
        if failed_items and self.devices:
            logger.info(f"=== Autonomous Retry Pass: Retrying {len(failed_items)} failed items ===")
            retry_collector = MarketCollector(instance_name=DEVICE_TO_INSTANCE.get(self.devices[0], self.devices[0]), use_adb=True)
            try:
                for f_item in failed_items:
                    try:
                        retry_collector.run_query_collection(f_item, max_pages=max_pages, target_tab=target_tab)
                    except Exception as e:
                        logger.error(f"Retry failed for '{f_item}': {e}")
            finally:
                retry_collector.shutdown()

        # Autonomous Tier Evaluation Pass
        try:
            evaluator = TierEvaluator()
            evaluator.evaluate_and_update_watchlist()
        except Exception as e:
            logger.debug(f"Tier re-evaluation error: {e}")
