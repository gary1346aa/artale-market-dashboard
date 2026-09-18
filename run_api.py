import sys
import io
import argparse
from pathlib import Path

# Ensure UTF-8 output in Windows PowerShell/CMD
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from aiohttp import web
from src.api_server import create_app

def main():
    parser = argparse.ArgumentParser(description="Artale Market K-Line Image API Service")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="Port to bind (default: 8080)")
    args = parser.parse_args()

    app = create_app()
    print(f"==================================================")
    print(f" Artale Market K-Line Image API Server")
    print(f" Local: http://127.0.0.1:{args.port}")
    print(f" Endpoints:")
    print(f"   - GET /api/kline/<item_name>/<1h|4h|1d>.png")
    print(f"   - GET /api/items")
    print(f"   - GET /api/health")
    print(f"==================================================")
    web.run_app(app, host=args.host, port=args.port)

if __name__ == "__main__":
    main()
