# Artale Market Analysis & Trading Intelligence System

[![GitHub Pages](https://img.shields.io/badge/Live%20Dashboard-GitHub%20Pages-success?style=for-the-badge&logo=github)](https://gary1346aa.github.io/artale-market-dashboard/)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20ADB-blue?style=for-the-badge)](#)
[![Python](https://img.shields.io/badge/Python-3.11%2B-informational?style=for-the-badge&logo=python)](https://www.python.org/)
[![Database](https://img.shields.io/badge/Storage-SQLite%20(WAL%20Mode)-orange?style=for-the-badge&logo=sqlite)](https://www.sqlite.org/)

An automated, high-speed market intelligence, OCR extraction, candlestick aggregation, and real-time dashboard pipeline for **MapleStory Worlds - Artale**.

---

## 🌟 Key Features & Architecture

### 1. 100% Silent Background ADB Automation
- **Zero Mouse Hijacking**: All input (`tap`, `keyevent`) is injected directly via Android Debug Bridge (`adb.exe`).
- **Zero Window Focus Stealing**: Runs completely in the background without minimizing your current work, moving your cursor, or interrupting PC usage.
- **Native Unicode Chinese Input**: Injects complex Traditional Chinese search keywords directly via `ADBKeyBoard.apk` (`am broadcast -a ADB_INPUT_B64`), bypassing host clipboard latency and phantom glyph issues.
- **Robust Modal & Dim Validation**: Intelligent screen-dimming detection distinguishes active modals from table content, preventing spurious keystrokes and avoiding unwanted lobby exit prompts.

### 2. Scalable Multi-Instance Parallel Collector
- **Dynamic Work-Stealing Queue**: Auto-detects all attached ADB devices and scales collection across $N \ge 2$ instances concurrently.
- **High-Speed Execution**: 
  - **~1.1s per page** end-to-end (SurfaceFlinger screencap + ROI crop + OCR + database write + page flip).
  - **~24.5s per item** across 22 full auction pages (2 active listing pages + 20 transaction history pages).
- **Quota Isolation**: Independent daily query quota management per ADB instance (500 queries/instance).

### 3. Concurrency-Safe Financial Storage
- **SQLite Write-Ahead Logging (WAL)**: `PRAGMA journal_mode=WAL; synchronous=NORMAL; timeout=30.0` enables seamless multi-threaded concurrent writes from all parallel workers without locking.
- **Automated Pre-Run Backups**: Creates timestamped snapshots in `data/backups/` prior to every collection run, retaining the 30 most recent recovery points.
- **Preserved Historical Data**: Continuous trade execution history and order book depth tracking across all watchlist items.

### 4. Adaptive Tiered Scheduling (Hourly Daemon)
- **Velocity-Driven Tiers**: Items are evaluated based on trading velocity and scheduled according to roll-off risk:
  - **Tier 1 (Ultra-High)**: Every **1 Hour** (Raid tickets, fast consumables, high-volume ores/crystals).
  - **Tier 2 (High)**: Every **4 Hours** (Stat-resets, mega speakers, mainstream 60%/70% scrolls).
  - **Tier 3 (Moderate)**: Every **12 Hours** (Accessory & 30% weapon scrolls).
  - **Tier 4 (Low / Sparse)**: Every **24 Hours** (Niche & long-tail scrolls).
- **Background Daemon (`schedule_prompt_daemon.ps1`)**: Fires on the hour (`00:00, 01:00, 02:00, ...`). Displays an interactive prompt with a 30-second unattended countdown that automatically defaults to full collection.

### 5. Binance-Style Web Dashboard
- **Interactive Candlestick Charts**: Built using TradingView's `Lightweight Charts` for multi-interval historical price action.
- **Live Market Highlights**: Real-time 24h Hot Volume, 24h Top Gainers/Losers, Lowest Asks, Spreads, and Order Depth.
- **Automated Git Sync**: Aggregates candlestick data and pushes rendered dashboards directly to GitHub Pages after every collection cycle.

---

## 🚀 Quick Start & Launchers

| Launcher Script | Description |
| :--- | :--- |
| **[`start_scheduled_tracker.bat`](start_scheduled_tracker.bat)** | **Starts the Hourly Background Daemon**. Runs 100% silently in the background, executing `both + due` every hour on the hour with zero interruption to PC use. |
| **[`run_collector_now.bat`](run_collector_now.bat)** | **One-Click Due Items Scan**. Immediately scans all currently due items (Both: Asks + Trades) in parallel ADB mode with zero prompts. |
| **[`run_all_items.bat`](run_all_items.bat)** | **One-Click Full Catalog Scan**. Scans the entire watchlist of all items (Both: Asks + Trades) in parallel ADB mode with zero prompts. |
| **[`run_auto.bat`](run_auto.bat)** | **Automated Pipeline Runner**. Runs collection (`both + due`), aggregates K-lines, builds dashboard, and syncs to GitHub Pages. |
| **[`stop_scheduled_tracker.bat`](stop_scheduled_tracker.bat)** | **Stops the Background Daemon**. Safely terminates any running scheduler processes. |

---

## 💻 CLI Usage

Direct command-line execution for advanced operations:

```bash
# 1. Parallel collection for all currently due items (Default: all attached ADB devices)
python run_collector.py --due --target-tab both

# 2. Collect a specific watchlist tier (e.g., Tier 1 Ultra-High)
python run_collector.py --tier 1 --pages 2 --target-tab both

# 3. Query a single specific item across 5 pages
python run_collector.py --query "突襲額外獎勵票券" --pages 5 --target-tab both

# 4. Limit parallel concurrency to 2 workers
python run_collector.py --due --parallel 2

# 5. Run aggregation & regenerate dashboard manually
python -m storage.aggregator
python dashboard.py

# 6. Run Bazel tests
bazel test //tests:all
```

---

## 📁 Repository Structure

```
artale_market_tracker/
├── assets/                    # Android IME helper and dashboard icons
├── cli/                       # Command-line entrypoints (collector, query, calibrate)
├── config/                    # Coordinates, layouts, and global settings
├── core/                      # Domain models, watchlist, and categorization
├── driver/                    # ADB device drivers and window managers
├── pipeline/                  # Auction scraping pipelines and parallel worker pool
├── recognition/               # Digit Engine, glyph tables, and text OCR
├── server/                    # REST API backend server
├── storage/                   # SQLite WAL database, schemas, and OHLCV aggregator
├── visualization/             # K-line plotter and dashboard exporter
├── scripts/                   # Accuracy verification and dataset benchmark tools
├── tests/                     # 18-target Bazel & unittest automated test suite
├── dashboard.html             # Binance-style interactive frontend template
├── items_watchlist.json       # Tracked items with tier intervals & timestamps
├── run_collector.py           # Unified collection CLI interface
├── run_auto.ps1               # Automated collection, aggregation & sync pipeline
└── schedule_prompt_daemon.ps1 # Unattended hourly scheduler daemon
```

---

## 📊 Live Production Dashboard

The live interactive dashboard is hosted on GitHub Pages:  
👉 **[https://gary1346aa.github.io/artale-market-dashboard/](https://gary1346aa.github.io/artale-market-dashboard/)**
