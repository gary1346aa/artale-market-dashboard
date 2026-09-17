import queue
import threading
import time
import logging
from typing import Optional
from PIL import Image
from .parser import MarketParser
from .database import save_active_listings, save_matched_trades
from .dataset_logger import save_dataset_frame

logger = logging.getLogger("ArtaleCollector")

class AsyncOcrWorker:
    """
    Background worker that ingests screenshot frames from pagination,
    parses item tables asynchronously via MarketParser, and persists records to SQLite.
    Guarantees FIFO order and serialized SQLite database writes.
    """
    def __init__(self):
        self._queue = queue.Queue()
        self._last_sig = None
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._worker_loop, daemon=True, name="AsyncOcrWorker")
        self._thread.start()

    def submit(self, frame: Image.Image, tab: str, page_num: int, item_name: Optional[str] = None, device_id: Optional[str] = None):
        """
        Enqueues a captured frame for background OCR parsing and DB persistence.
        """
        self._queue.put((frame, tab, page_num, item_name, device_id))

    def _worker_loop(self):
        while True:
            item = self._queue.get()
            if item is None:
                self._queue.task_done()
                break

            if len(item) == 5:
                frame, tab, page_num, item_name, device_id = item
            else:
                frame, tab, page_num, item_name = item
                device_id = None

            try:
                # Persist raw frame to permanent test dataset
                save_dataset_frame(frame, item_name=item_name, tab=tab, page_num=page_num, device_id=device_id)

                parser = MarketParser(frame, item_name=item_name)
                res = parser.parse()
                records = res.get("records", [])

                with self._lock:
                    if tab == "market":
                        sig = tuple((r.item_name, r.matched_unit_price, r.trade_time) for r in records)
                        if self._last_sig is not None and sig and sig == self._last_sig:
                            logger.debug(f"[市價] Page {page_num} duplicate signature detected (unchanged). Skipping save.")
                        else:
                            save_matched_trades(records)
                            logger.debug(f"[市價] Async parsed & saved {len(records)} completed trades from page {page_num}.")
                            if records:
                                self._last_sig = sig
                    else:
                        sig = tuple((r.item_name, r.unit_price, r.total_price) for r in records)
                        if self._last_sig is not None and sig and sig == self._last_sig:
                            logger.debug(f"[查詢] Page {page_num} duplicate signature detected (unchanged). Skipping save.")
                        else:
                            save_active_listings(records)
                            logger.debug(f"[查詢] Async parsed & saved {len(records)} active listings from page {page_num}.")
                            if records:
                                self._last_sig = sig
            except Exception as e:
                import os, datetime
                err_dir = os.path.join("scratch", "debug_errors")
                os.makedirs(err_dir, exist_ok=True)
                ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                safe_name = "".join(c for c in (item_name or "unknown") if c.isalnum() or c in ("-", "_"))
                err_path = os.path.join(err_dir, f"err_{safe_name}_{tab}_p{page_num}_{ts}.png")
                try:
                    frame.save(err_path)
                    logger.error(f"[AsyncOcrWorker] Saved failed frame to: {os.path.abspath(err_path)}")
                except Exception as save_err:
                    logger.error(f"[AsyncOcrWorker] Could not save failed frame: {save_err}")
                logger.error(f"Error in Async OCR worker on page {page_num} for '{item_name}': {e}")
            finally:
                self._queue.task_done()

    def wait_all(self):
        """
        Blocks until all queued frames are fully parsed and saved.
        Polls with short sleeps to remain responsive to KeyboardInterrupt / Ctrl+C.
        """
        while self._queue.unfinished_tasks > 0:
            time.sleep(0.02)

    def reset_signature(self):
        """
        Resets previous page signature. Should be called between queries or tabs.
        """
        with self._lock:
            self._last_sig = None

    def shutdown(self):
        """
        Flushes pending tasks and cleanly shuts down worker thread.
        """
        self.wait_all()
        self._queue.put(None)
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)
