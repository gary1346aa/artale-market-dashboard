"""Backwards compatibility shim for legacy src.tier_evaluator imports."""

from core.watchlist import (
    WatchlistManager,
    calculate_tier,
    get_due_items,
    get_item_last_updated,
    load_watchlist,
)

__all__ = [
    "WatchlistManager",
    "calculate_tier",
    "get_due_items",
    "get_item_last_updated",
    "load_watchlist",
]
