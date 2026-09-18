import asyncio
import io
import logging
import urllib.parse
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from aiohttp import web
from src.kline_plotter import generate_kline_plot_bytes, DB_PATH

logger = logging.getLogger("artale_api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

async def handle_health(request: web.Request) -> web.Response:
    """Health check endpoint."""
    return web.json_response({
        "status": "ok",
        "service": "artale_kline_api",
        "timestamp": datetime.now().isoformat(),
        "db_connected": DB_PATH.exists()
    })

async def handle_kline_image(request: web.Request) -> web.Response:
    """
    Renders high-resolution K-line candlestick chart image.
    Supports both path parameters and query parameters:
      - /api/kline/{item_name}/{timeframe}.png
      - /api/kline?item={item_name}&timeframe={timeframe}
    """
    # 1. Extract and decode item_name and timeframe
    item_name = request.match_info.get("item_name") or request.query.get("item")
    timeframe = request.match_info.get("timeframe") or request.query.get("timeframe", "1h")

    if not item_name:
        return web.json_response(
            {"error": "Missing item_name. Usage: /api/kline/{item_name}/{timeframe}.png"},
            status=400
        )

    # Clean extension if passed in path (e.g. 1h.png -> 1h)
    if timeframe.endswith(".png"):
        timeframe = timeframe[:-4]

    # Normalize timeframe
    timeframe = timeframe.lower()
    if timeframe not in ("1h", "4h", "1d"):
        return web.json_response(
            {"error": f"Invalid timeframe '{timeframe}'. Supported timeframes: 1h, 4h, 1d."},
            status=400
        )

    # Decode URL-encoded characters (e.g. %E5%8A%9B%E9%87%8F%E6%B0%B4%E6%99%B6 -> 力量水晶)
    item_name = urllib.parse.unquote(item_name).strip()

    # Engine selection: 'pillow' (default, high-performance financial render) or 'html'
    engine = request.query.get("engine", "pillow").lower()
    default_w = 1800
    default_h = 2400
    width = int(request.query.get("width", default_w))
    height = int(request.query.get("height", default_h))
    scale_raw = float(request.query.get("scale", 125 if engine == "html" else 100))
    scale = scale_raw / 100.0 if scale_raw > 10 else scale_raw

    try:
        if engine == "html":
            try:
                from src.html_snapshot import capture_html_snapshot
                png_bytes = await asyncio.to_thread(
                    capture_html_snapshot,
                    item_name=item_name,
                    timeframe=timeframe,
                    width=width,
                    height=height,
                    scale_factor=scale
                )
            except Exception as e_html:
                logger.warning(f"HTML snapshot failed ({e_html}), falling back to Pillow engine.")
                png_bytes = await asyncio.to_thread(
                    generate_kline_plot_bytes,
                    item_name=item_name,
                    timeframe=timeframe,
                    width=width,
                    height=height
                )
        else:
            png_bytes = await asyncio.to_thread(
                generate_kline_plot_bytes,
                item_name=item_name,
                timeframe=timeframe,
                width=width,
                height=height
            )

        return web.Response(
            body=png_bytes,
            content_type="image/png",
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
                "Content-Disposition": f'inline; filename="{urllib.parse.quote(item_name)}_{timeframe}.png"'
            }
        )
    except ValueError as ve:
        return web.json_response(
            {"error": str(ve)},
            status=404
        )
    except Exception as e:
        logger.exception(f"Error rendering chart for {item_name} ({timeframe}): {e}")
        return web.json_response(
            {"error": f"Internal server error: {str(e)}"},
            status=500
        )

async def handle_list_items(request: web.Request) -> web.Response:
    """Lists all available items in the market database."""
    import sqlite3
    try:
        def fetch_items():
            with sqlite3.connect(DB_PATH) as conn:
                c = conn.cursor()
                c.execute("""
                    SELECT item_name, count(DISTINCT timeframe), count(*), max(bucket_time)
                    FROM kline_candles
                    GROUP BY item_name
                    ORDER BY item_name ASC
                """)
                return [
                    {
                        "item_name": r[0],
                        "available_timeframes": r[1],
                        "total_candles": r[2],
                        "latest_data_time": r[3]
                    }
                    for r in c.fetchall()
                ]

        items = await asyncio.to_thread(fetch_items)
        return web.json_response({"total": len(items), "items": items})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/api/health", handle_health)
    app.router.add_get("/api/items", handle_list_items)
    app.router.add_get("/api/kline/{item_name}/{timeframe}", handle_kline_image)
    app.router.add_get("/api/kline/{item_name}", handle_kline_image)
    app.router.add_get("/api/kline", handle_kline_image)
    return app

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Artale Market K-Line Image API Server")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host IP to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="Port to bind (default: 8080)")
    args = parser.parse_args()

    app = create_app()
    logger.info(f"Starting K-Line API Server on http://{args.host}:{args.port}")
    web.run_app(app, host=args.host, port=args.port)

if __name__ == "__main__":
    main()
