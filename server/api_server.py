"""Asynchronous REST API server for candlestick images and market data.

Provides HTTP endpoints for rendering high-resolution candlestick charts,
fetching JSON market summaries, and checking service health via aiohttp.
"""

import asyncio
from datetime import datetime
import io
import logging
from pathlib import Path
from typing import Optional
import urllib.parse

from aiohttp import web

from config.settings import DB_PATH
from visualization.dashboard_exporter import export_dashboard_data
from visualization.kline_plotter import generate_kline_plot_bytes

_logger = logging.getLogger(__name__)


async def handle_health(request: web.Request) -> web.Response:
    """Health check endpoint returning service status and database existence.

    Args:
        request: Incoming aiohttp web request.

    Returns:
        JSON response with health details.
    """
    return web.json_response({
        "status": "ok",
        "service": "artale_kline_api",
        "timestamp": datetime.now().isoformat(),
        "db_connected": DB_PATH.exists(),
    })


async def handle_kline_image(request: web.Request) -> web.Response:
    """Renders and streams high-resolution candlestick chart image as PNG.

    Supported routes:
      - /api/kline/{item_name}/{timeframe}.png
      - /api/kline?item={item_name}&timeframe={timeframe}

    Args:
        request: Incoming aiohttp web request.

    Returns:
        PNG image binary stream or JSON error response.
    """
    item_name = request.match_info.get("item_name") or request.query.get("item")
    timeframe = request.match_info.get("timeframe") or request.query.get(
        "timeframe", "1h"
    )

    if not item_name:
        return web.json_response(
            {"error": "Missing item_name. Usage: /api/kline/{item_name}/{timeframe}.png"},
            status=400,
        )

    if timeframe.endswith(".png"):
        timeframe = timeframe[:-4]

    timeframe = timeframe.lower()
    if timeframe not in ("1h", "4h", "1d"):
        return web.json_response(
            {"error": f"Invalid timeframe '{timeframe}'. Supported: 1h, 4h, 1d."},
            status=400,
        )

    item_name = urllib.parse.unquote(item_name).strip()
    width = int(request.query.get("width", 1800))
    height = int(request.query.get("height", 2400))

    try:
        png_bytes = await asyncio.to_thread(
            generate_kline_plot_bytes,
            item_name=item_name,
            timeframe=timeframe,
            width=width,
            height=height,
        )
        return web.Response(
            body=png_bytes,
            content_type="image/png",
            headers={
                "Cache-Control": "public, max-age=60",
                "X-Render-Engine": "Pillow-1800x2400",
            },
        )
    except ValueError as err:
        return web.json_response({"error": str(err)}, status=404)
    except Exception as err:
        _logger.error(f"API rendering error for '{item_name}': {err}")
        return web.json_response(
            {"error": f"Failed to render chart: {str(err)}"}, status=500
        )


async def handle_dashboard_data(request: web.Request) -> web.Response:
    """Returns complete JSON market overview and candlestick datasets."""
    try:
        data = await asyncio.to_thread(export_dashboard_data)
        return web.json_response(data)
    except Exception as err:
        _logger.error(f"Failed to export dashboard data: {err}")
        return web.json_response({"error": str(err)}, status=500)


def create_app() -> web.Application:
    """Constructs and configures the aiohttp web application.

    Returns:
        Configured aiohttp web.Application.
    """
    app = web.Application()
    app.router.add_get("/health", handle_health)
    app.router.add_get(r"/api/kline/{item_name}/{timeframe:\d+[hd]\.png}", handle_kline_image)
    app.router.add_get(r"/api/kline/{item_name}/{timeframe:\d+[hd]}", handle_kline_image)
    app.router.add_get("/api/kline", handle_kline_image)
    app.router.add_get("/api/dashboard/data", handle_dashboard_data)
    return app


def start_server(host: str = "0.0.0.0", port: int = 8080) -> None:
    """Starts the HTTP API server synchronously.

    Args:
        host: Network interface to bind.
        port: TCP port to listen on.
    """
    app = create_app()
    _logger.info(f"Starting Artale K-Line API Server on http://{host}:{port}")
    web.run_app(app, host=host, port=port)
