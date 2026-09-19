"""Passive observer for hotkey-based manual market capture.

Listens for F9 (manual snapshot) or F10 (continuous observation) hotkeys
and parses the visible game window without simulating mouse or keyboard inputs.
"""

import logging
import time
from typing import Optional

from pynput import keyboard

from driver.window_driver import WindowManager
from recognition.table_parser import MarketParser
from storage.database import init_db, save_active_listings, save_matched_trades

_logger = logging.getLogger(__name__)


class PassiveMarketMonitor:
    """Records market data on hotkeys without synthetic input injection.

    Attributes:
        win_mgr: WindowManager instance for desktop screen grabbing.
        is_monitoring: Boolean flag indicating if background watch is active.
    """

    def __init__(self, window_mgr: Optional[WindowManager] = None) -> None:
        """Initializes PassiveMarketMonitor."""
        self.win_mgr = window_mgr or WindowManager()
        self.is_monitoring = False
        init_db()

    def capture_and_save(self) -> int:
        """Grabs client screen, parses table rows, and saves to database.

        Returns:
            Number of records saved.
        """
        frame = self.win_mgr.capture_frame()
        if not frame:
            _logger.warning("Could not capture game window.")
            return 0

        parser = MarketParser(frame)
        res = parser.parse()
        tab = res.get("tab", "query")
        records = res.get("records", [])

        if not records:
            _logger.info("No market listings or trades detected on screen.")
            return 0

        if tab == "market":
            save_matched_trades(records)
            _logger.info("Saved %d matched trades into database.", len(records))
        else:
            save_active_listings(records)
            _logger.info("Saved %d active listings into database.", len(records))

        return len(records)

    def on_hotkey_manual(self) -> None:
        """Handles F9 manual snapshot."""
        _logger.info("[F9] Manual capture triggered!")
        self.capture_and_save()

    def on_hotkey_toggle(self) -> None:
        """Handles F10 monitoring toggle."""
        self.is_monitoring = not self.is_monitoring
        state = "ACTIVATED" if self.is_monitoring else "DEACTIVATED"
        _logger.info("[F10] Continuous watcher %s.", state)

    def start_listener(self) -> None:
        """Starts the blocking pynput global keyboard listener."""
        _logger.info("Passive Market Monitor listening (F9: snapshot, F10: toggle)...")

        def for_canonical(f):
            return lambda k: f(l.canonical(k))

        hotkeys = {
            keyboard.Key.f9: self.on_hotkey_manual,
            keyboard.Key.f10: self.on_hotkey_toggle,
        }

        with keyboard.Listener(
            on_press=lambda k: hotkeys.get(k, lambda: None)()
        ) as l:
            l.join()
