"""CLI entry point for running the Artale Market REST API server."""

import argparse
import logging

from config.settings import setup_logging
from server.api_server import start_server


def main() -> None:
    """Parses arguments and launches API server."""
    parser = argparse.ArgumentParser(
        description="Artale Market Tracker - K-Line REST API Server",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Network interface to bind server to.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="TCP port to listen on.",
    )

    args = parser.parse_args()
    setup_logging(level=logging.INFO)
    start_server(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
