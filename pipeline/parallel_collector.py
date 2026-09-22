"""Multi-worker parallel collection orchestrator with autonomous per-instance lifecycles.

Spawns independent worker threads across N LDPlayer emulator instances. Each worker
independently manages its own end-to-end lifecycle:
(Launch -> Bootstrap to Free Market -> Work-stealing collection -> Teardown)
without blocking barriers across instances.
"""

import logging
from pathlib import Path
import queue
import threading
import time
from typing import Dict, List, Optional, Tuple

from driver.adb_driver import AdbDriver
from driver.emulator_controller import (
    EmulatorController,
    resolve_device_serial,
)
from driver.game_bootstrapper import GameBootstrapper
from pipeline.collector import (
    INSTANCE_TO_DEVICE,
    MarketCollector,
)

import unicodedata

_logger = logging.getLogger(__name__)

DEVICE_TO_INSTANCE: Dict[str, str] = {v: k for k, v in INSTANCE_TO_DEVICE.items()}
DEFAULT_TRACKER_INSTANCES: List[str] = ["槍手", "打火機", "弩手"]
DEFAULT_TRACKER_DEVICES: List[str] = ["emulator-5560", "emulator-5562", "emulator-5568"]


def get_display_width(text: str) -> int:
    """Calculates display width taking East Asian fullwidth/wide characters into account."""
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in text)


def pad_display_width(text: str, target_width: int) -> str:
    """Pads text to target visual width using ASCII spaces."""
    dw = get_display_width(text)
    pad = max(0, target_width - dw)
    return text + (" " * pad)


class ParallelCollector:
    """Orchestrates multi-instance dynamic work-stealing collection across emulators.

    Each worker instance operates on an autonomous lifecycle:
    1. Boots instance if not running / cold-boot enabled.
    2. Bootstraps to Free Market independently.
    3. Joins the work-stealing task queue immediately upon readiness.
    4. Safely terminates its own instance upon queue drain or quota exhaustion.

    Attributes:
        use_adb: Whether to use ADB driver.
        cold_boot: Whether to cold-boot instances.
        bootstrap: Whether to bootstrap instances to Free Market.
        kill_after: Whether to terminate instances upon completion.
        worker_targets: List of (instance_name, device_id) pairs.
    """

    def __init__(
        self,
        max_workers: Optional[int] = None,
        devices: Optional[List[str]] = None,
        instances: Optional[List[str]] = None,
        use_adb: bool = True,
        cold_boot: bool = False,
        bootstrap: bool = False,
        kill_after: bool = False,
        controller: Optional[EmulatorController] = None,
    ) -> None:
        """Initializes ParallelCollector with worker targets and lifecycle settings."""
        self.use_adb = use_adb
        self.cold_boot = cold_boot
        self.bootstrap = bootstrap
        self.kill_after = kill_after
        self.controller = controller or EmulatorController()

        self.worker_targets: List[Tuple[str, str]] = []

        if instances:
            for inst in instances:
                dev = (
                    INSTANCE_TO_DEVICE.get(inst)
                    or resolve_device_serial(inst)
                    or "emulator-5560"
                )
                self.worker_targets.append((inst, dev))
        elif devices:
            for dev in devices:
                inst = DEVICE_TO_INSTANCE.get(dev, dev)
                self.worker_targets.append((inst, dev))
        else:
            if self.use_adb:
                attached = AdbDriver.list_attached_devices()
                if self.cold_boot or not attached:
                    for inst in DEFAULT_TRACKER_INSTANCES:
                        dev = INSTANCE_TO_DEVICE.get(inst, "emulator-5560")
                        self.worker_targets.append((inst, dev))
                else:
                    active_devs = (
                        [d for d in DEFAULT_TRACKER_DEVICES if d in attached]
                        or attached
                    )
                    for dev in active_devs:
                        inst = DEVICE_TO_INSTANCE.get(dev, dev)
                        self.worker_targets.append((inst, dev))
            else:
                self.worker_targets.append(("legacy", "legacy"))

        if max_workers and max_workers > 0:
            self.worker_targets = self.worker_targets[:max_workers]

        self.devices = [dev for _, dev in self.worker_targets]
        _logger.info(
            f"ParallelCollector initialized with {len(self.worker_targets)} worker(s): "
            f"{[f'{inst} ({dev})' for inst, dev in self.worker_targets]}"
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
        w_total = len(str(len(keywords)))
        w_batch = len(str(total_items))
        max_inst_w = max(
            [get_display_width(inst) for inst, _ in self.worker_targets] or [6]
        )

        def worker_thread(inst_name: str, device_id: str) -> None:
            nonlocal completed_count
            inst_tag = pad_display_width(inst_name, max_inst_w)
            _logger.info(
                f"[{inst_tag}] Starting asynchronous worker pipeline ({device_id})..."
            )

            # 1. Cold boot / Ensure instance is running
            if self.cold_boot or (
                self.controller and not self.controller.is_running(inst_name)
            ):
                _logger.info(f"[{inst_tag}] Booting emulator instance...")
                if self.controller:
                    self.controller.trigger_launch(inst_name)
                    # Stagger launch dispatches to avoid COM server lock collisions
                    time.sleep(2.5)
                    if not self.controller.wait_for_ready(inst_name, max_wait_sec=60):
                        _logger.error(
                            f"[{inst_tag}] Timed out waiting for boot. Worker aborting."
                        )
                        return

            # 2. Bootstrap to Free Market
            if self.bootstrap:
                _logger.info(f"[{inst_tag}] Bootstrapping to Free Market...")
                bootstrapper = GameBootstrapper(
                    adb=AdbDriver(device_id=device_id),
                    controller=self.controller,
                    instance_name=inst_name,
                )
                if not bootstrapper.bootstrap_to_free_market(
                    clean_reboot=False, max_timeout_sec=160
                ):
                    _logger.error(
                        f"[{inst_tag}] Failed to reach Free Market. Worker aborting."
                    )
                    if self.kill_after and self.controller:
                        self.controller.quit_instance(inst_name)
                    return

            # 3. Enter Auction House & Check Quota
            _logger.info(f"[{inst_tag}] Reached Free Market. Entering Auction House...")
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
                    f"[{inst_tag}] Auction House entry attempt {attempt}/3 failed. Retrying..."
                )
                time.sleep(3.0)

            if not ready:
                _logger.error(
                    f"[{inst_tag}] Could not enter Auction House. Worker aborting."
                )
                if self.kill_after and self.controller:
                    self.controller.quit_instance(inst_name)
                return

            rem = collector.get_screen_quota()
            if rem is not None and rem < 2:
                _logger.warning(
                    f"[{inst_tag}] Initial search quota exhausted ({rem} < 2). Retiring worker."
                )
                collector.leave_auction()
                collector.shutdown()
                if self.kill_after and self.controller:
                    self.controller.quit_instance(inst_name)
                return

            _logger.info(f"[{inst_tag}] Ready. Draining task queue dynamically...")
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
                        f"[{inst_tag}] -> Scanning [{idx:>{w_total}}/{total_total}] (Batch: {curr_progress:>{w_batch}}/{total_items}): '{item}'"
                    )

                    try:
                        ok = collector.run_query_collection(
                            item,
                            max_pages=max_pages,
                            target_tab=target_tab,
                        )
                        if not ok:
                            _logger.warning(
                                f"[{inst_tag}] Quota exhausted on '{item}'. Re-queueing and retiring worker."
                            )
                            task_queue.put((idx, total_total, item))
                            collector.leave_auction()
                            collector.shutdown()
                            if self.kill_after and self.controller:
                                self.controller.quit_instance(inst_name)
                            return
                    except Exception as err:
                        _logger.error(
                            f"[{inst_tag}] Error processing '{item}': {err}"
                        )
                        with failed_lock:
                            failed_items.append(item)
                    finally:
                        task_queue.task_done()
                    time.sleep(1.2)
            finally:
                _logger.info(f"[{inst_tag}] Exiting Auction House...")
                collector.shutdown()
                if self.kill_after and self.controller:
                    _logger.info(f"[{inst_tag}] Terminating instance...")
                    self.controller.quit_instance(inst_name)

        # Launch workers concurrently
        threads: List[threading.Thread] = []
        for inst, dev in self.worker_targets:
            t = threading.Thread(
                target=worker_thread,
                args=(inst, dev),
                name=f"Worker-{inst}",
                daemon=True,
            )
            threads.append(t)
            t.start()
            time.sleep(0.2)

        for t in threads:
            t.join()

        _logger.info("Parallel catalog collection completed.")

    def shutdown(self) -> None:
        """Graceful shutdown hook for collector instances."""
        if self.kill_after and self.controller:
            for inst, _ in self.worker_targets:
                if self.controller.is_running(inst):
                    self.controller.quit_instance(inst)
