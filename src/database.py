"""Backwards compatibility shim for legacy src.database imports."""

from storage.database import (
    DB_PATH,
    SCHEMA_SQL,
    DatabaseManager,
    get_connection,
    init_database,
    open_db,
)

__all__ = [
    "DB_PATH",
    "SCHEMA_SQL",
    "DatabaseManager",
    "get_connection",
    "init_database",
    "open_db",
]
