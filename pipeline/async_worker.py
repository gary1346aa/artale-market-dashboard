"""Producer-consumer background worker for asynchronous OCR and persistence.

Ingests captured screenshot frames from page flipping, parses tabular data
asynchronously using MarketParser, and serializes writes to SQLite.
"""

from datetime import datetime
import logging
from pathlib import Path
import queue
import threading
import time
from typing import Any, Optional, Tuple

from PIL import Image

from config.settings import PROJECT_ROOT
from core.models import ActiveListing, MatchedTrade
from recognition.table_parser import MarketParser
from storage.database import save_active_listings, save_matched_trades

_logger = logging.getLogger(__name__)

DEBUG_ERRORS_DIR: Path = PROJECT_ROOT / "scratch" / "debug_errors"


class AsyncOcrWorker:
    """Background worker that processes screenshot frames asynchronously.

    Guarantees FIFO order and serialized SQLite database writes.
    """

    def __init__(self) -> None:
        """Initializes AsyncOcrWorker and starts worker thread."""
        self._queue: queue.Queue[
            Optional[Tuple[Image.Image, str, int, Optional[str], Optional[str]]]
        ] = queue.Queue()
        self._last_sig: Optional[Tuple[Any, ...]] = None
        self._lock = threading.Lock()
        self._thread = threading.Thread(
            target=self._worker_loop, daemon=True, name="AsyncOcrWorker"
        )
        self._thread.start()

    def submit(
        self,
        frame: Image.Image,
        tab: str,
        page_num: int,
        item_name: Optional[str] = None,
        device_id: Optional[str] = None,
    ) -> None:
        """Enqueues a captured frame for background OCR and DB storage.

        Args:
            frame: PIL RGB Image.
            tab: 'query' or 'market'.
            page_num: Table page index.
            item_name: Optional expected item name.
            device_id: Optional emulator device serial.
        """
        self._queue.put((frame, tab, page_num, item_name, device_id))

    def _worker_loop(self) -> None:
        """Continuously pulls frames from queue and executes parsing."""
        while True:
            item = self._queue.get()
            if item is None:
                self._queue.task_done()
                break

            frame, tab, page_num, item_name, device_id = item

            try:
                parser = MarketParser(frame, item_name=item_name)
                res = parser.parse()
                records = res.get("records", [])

                with self._lock:
                    if tab == "market":
                        sig = tuple(
                            (r.item_name, r.matched_unit_price, r.trade_time)
                            for r in records
                            if isinstance(r, MatchedTrade)
                        )
                        if (
                            self._last_sig is not None
                            and sig
                            and sig == self._last_sig
                        ):
                            _logger.debug(
                                "[市價] Page %d duplicate signature detected. Skipping save.",
                                page_num,
                            )
                        else:
                            save_matched_trades(records)
                            _logger.debug(
                                "[市價] Async parsed & saved %d trades from page %d.",
                                len(records),
                                page_num,
                            )
                            if records:
                                self._last_sig = sig
                    else:
                        sig = tuple(
                            (r.item_name, r.unit_price, r.total_price)
                            for r in records
                            if isinstance(r, ActiveListing)
                        )
                        if (
                            self._last_sig is not None
                            and sig
                            and sig == self._last_sig
                        ):
                            _logger.debug(
                                "[查詢] Page %d duplicate signature detected. Skipping save.",
                                page_num,
                            )
                        else:
                            save_active_listings(records)
                            _logger.debug(
                                "[查詢] Async parsed & saved %d active listings from page %d.",
                                len(records),
                                page_num,
                            )
                            if records:
                                self._last_sig = sig
            except Exception as err:
                try:
                    DEBUG_ERRORS_DIR.mkdir(parents=True, exist_ok=True)
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    safe_name = "".join(
                        c
                        for c in (item_name or "unknown")
                        if c.isalnum() or c in ("-", "_")
                    )
                    err_path = (
                        DEBUG_ERRORS_DIR
                        / f"err_{safe_name}_{tab}_p{page_num}_{ts}.png"
                    )
                    frame.save(err_path)
                    _logger.error(
                        "[AsyncOcrWorker] Saved failed frame to: %s",
                        err_path.resolve(),
                    )
                except Exception as save_err:
                    _logger.error(
                        "[AsyncOcrWorker] Could not save failed frame: %s",
                        save_err,
                    )
                _logger.error(
                    "Error in Async OCR worker on page %d for '%s': %s",
                    page_num,
                    item_name,
                    err,
                )
            finally:
                self._queue.task_done()

    def wait_all(self) -> None:
        """Blocks until all queued frames are fully parsed and saved."""
        while self._queue.unfinished_tasks > 0:
            time.sleep(0.02)

    def reset_signature(self) -> None:
        """Resets previous page signature between queries or tabs."""
        with self._lock:
            self._last_sig = None

    def shutdown(self) -> None:
        """Waits for pending tasks and terminates worker thread."""
        self.wait_all()
        self._queue.put(None)
        self._thread.join(timeout=3.0)
