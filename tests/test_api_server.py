"""Unit tests for REST API endpoints and candlestick chart streaming."""

import tempfile
import unittest
from pathlib import Path
import sqlite3

from aiohttp.test_utils import AioHTTPTestCase

from server.api_server import create_app
from storage.database import init_db


class TestApiServer(AioHTTPTestCase):
    """Tests for API server HTTP routes and response payloads."""

    async def get_application(self):
        return create_app()

    async def test_health_check(self):
        """Verify /health endpoint returns 200 and status ok."""
        resp = await self.client.get("/health")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["service"], "artale_kline_api")

    async def test_kline_missing_item(self):
        """Verify /api/kline without item parameter returns 400."""
        resp = await self.client.get("/api/kline")
        self.assertEqual(resp.status, 400)
        data = await resp.json()
        self.assertIn("error", data)

    async def test_kline_invalid_timeframe(self):
        """Verify /api/kline with invalid timeframe returns 400."""
        resp = await self.client.get("/api/kline?item=test&timeframe=5m")
        self.assertEqual(resp.status, 400)
        data = await resp.json()
        self.assertIn("Invalid timeframe", data["error"])

    async def test_kline_invalid_dimensions(self):
        """Verify /api/kline with non-integer dimensions returns 400."""
        resp = await self.client.get("/api/kline?item=test&timeframe=1h&width=abc")
        self.assertEqual(resp.status, 400)
        data = await resp.json()
        self.assertIn("Invalid width or height", data["error"])

    async def test_kline_nonexistent_item(self):
        """Verify /api/kline for non-existent item returns 404."""
        resp = await self.client.get("/api/kline?item=NonExistentItemXYZ&timeframe=1h")
        self.assertEqual(resp.status, 404)
        data = await resp.json()
        self.assertIn("No candlestick data available", data["error"])

    async def test_snapshot_alias_routes(self):
        """Verify /api/snapshot aliases route properly to kline handler."""
        resp = await self.client.get("/api/snapshot")
        self.assertEqual(resp.status, 400)


if __name__ == "__main__":
    unittest.main()
