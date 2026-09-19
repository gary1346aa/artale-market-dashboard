"""Root entry point for generating the Artale Market dashboard.

Delegates execution to the clean visualization package.
"""

from pathlib import Path
import sys

from config.settings import setup_logging
from visualization.dashboard_exporter import (
    export_dashboard_data,
    generate_dashboard_html,
)

if __name__ == "__main__":
    setup_logging()
    out = generate_dashboard_html()
    print(f"Dashboard successfully generated: {out}")
