"""REST API server package for Artale Market Tracker.

Exports aiohttp application factory and server startup entry points.
"""

def __getattr__(name: str):
    if name in ("create_app", "start_server", "handle_health", "handle_kline_image"):
        import server.api_server as s
        return getattr(s, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "create_app",
    "start_server",
    "handle_health",
    "handle_kline_image",
]
