import time
import logging
from typing import Optional
from pynput import keyboard
from .window_manager import WindowManager
from .parser import MarketParser
from .database import init_db, save_active_listings, save_matched_trades

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("PassiveMonitor")

class PassiveMarketMonitor:
    """
    Passive observer that records market data on hotkeys (F9) or continuous monitoring (F10)
    WITHOUT simulating any synthetic mouse clicks or keystrokes.
    """
    def __init__(self, window_mgr: Optional[WindowManager] = None):
        self.win_mgr = window_mgr or WindowManager()
        self.is_monitoring = False
        self.last_scraped_hash = None
        init_db()

    def capture_and_save(self) -> int:
        """
        Grabs active client screen, auto-detects tab, parses rows, and saves to DB.
        """
        frame = self.win_mgr.capture_frame()
        if not frame:
            logger.warning("Could not capture game window. Make sure Artale is visible.")
            return 0

        parser = MarketParser(frame)
        res = parser.parse()
        tab = res["tab"]
        records = res["records"]

        if not records:
            logger.info("No market listings or trade items detected on current screen.")
            return 0

        if tab == "market":
            save_matched_trades(records)
            logger.info(f"💾 [市價 Tab] Saved {len(records)} matched trades into database.")
        else:
            save_active_listings(records)
            logger.info(f"💾 [查詢 Tab] Saved {len(records)} active listings into database.")

        return len(records)

    def on_hotkey_manual(self):
        logger.info("⚡ [F9] Manual capture triggered!")
        self.capture_and_save()

    def on_hotkey_toggle(self):
        self.is_monitoring = not self.is_monitoring
        state = "ACTIVATED" if self.is_monitoring else "DEACTIVATED"
        logger.info(f"🔄 [F10] Continuous live watcher {state}.")

    def start_listener(self):
        """
        Starts listening for global hotkeys:
        - F9: Snapshot current market screen
        - F10: Toggle background interval watcher
        """
        logger.info("=" * 60)
        logger.info("PASSIVE MONITOR STARTED")
        logger.info("  [F9]  : Capture current market page (Query or Market tab)")
        logger.info("  [F10] : Toggle continuous auto-recording (every 2.5s)")
        logger.info("  [Ctrl+C in terminal] : Exit monitor")
        logger.info("=" * 60)

        hotkeys = keyboard.GlobalHotKeys({
            "<f9>": self.on_hotkey_manual,
            "<f10>": self.on_hotkey_toggle
        })
        hotkeys.start()

        try:
            while True:
                if self.is_monitoring:
                    self.capture_and_save()
                    time.sleep(2.5)
                else:
                    time.sleep(0.2)
        except KeyboardInterrupt:
            logger.info("Stopping Passive Monitor...")
        finally:
            hotkeys.stop()
