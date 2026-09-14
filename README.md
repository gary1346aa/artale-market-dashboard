# Artale Market Analysis & Trading Intelligence System

[![GitHub Pages](https://img.shields.io/badge/Live%20Dashboard-GitHub%20Pages-success?style=for-the-badge&logo=github)](https://gary1346aa.github.io/artale-market-dashboard/)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20LDPlayer%209%20%7C%20ADB-blue?style=for-the-badge)](https://www.ldplayer.net/)
[![Python](https://img.shields.io/badge/Python-3.11%2B-informational?style=for-the-badge&logo=python)](https://www.python.org/)
[![Database](https://img.shields.io/badge/Storage-SQLite%20(WAL%20Mode)-orange?style=for-the-badge&logo=sqlite)](https://www.sqlite.org/)

An automated, high-speed market intelligence, OCR extraction, candlestick aggregation, and real-time dashboard pipeline for **MapleStory Worlds - Artale**.

---

## 🌟 Key Features & Architecture

### 1. 100% Silent Background ADB Automation
- **Zero Mouse Hijacking**: All input (`tap`, `keyevent`) is injected directly into LDPlayer canvas instances via Android Debug Bridge (`adb.exe`).
- **Zero Window Focus Stealing**: Runs completely in the background without minimizing your current work, moving your cursor, or interrupting PC usage.
- **Native Unicode Chinese Input**: Injects complex Traditional Chinese search keywords directly via `ADBKeyBoard.apk` (`am broadcast -a ADB_INPUT_B64`), bypassing host clipboard latency and phantom glyph issues.
- **Robust Modal & Dim Validation**: Intelligent screen-dimming detection distinguishes active modals from table content, preventing spurious keystrokes and avoiding unwanted lobby exit prompts.

### 2. Scalable Multi-Instance Parallel Collector
- **Dynamic Work-Stealing Queue**: Auto-detects all attached emulators (`emulator-5558`, `emulator-5560`, ..., `emulator-5558+2N`) and scales collection across $N \ge 2$ instances concurrently.
- **High-Speed Execution**: 
  - **~1.1s per page** end-to-end (SurfaceFlinger screencap + ROI crop + OCR + database write + page flip).
  - **~24.5s per item** across 22 full auction pages (2 active listing pages + 20 transaction history pages).
- **Quota Isolation**: Independent daily query quota management per emulator instance (500 queries/instance).

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
| **[`start_scheduled_tracker.bat`](start_scheduled_tracker.bat)** | **Starts the Hourly Background Daemon**. Runs silently in background, prompting every hour on the hour. |
| **[`run_auto.bat`](run_auto.bat)** | **One-Click Due Item Scan**. Immediately scans all currently due items across attached emulators in parallel ADB mode. |
| **[`run_collector_now.bat`](run_collector_now.bat)** | **Interactive Launcher Menu**. Select Due-Only, Full Catalog, Specific Tier (1-4), or Single Item Query. |
| **[`test_scheduled_prompt.bat`](test_scheduled_prompt.bat)** | **Test Scheduler Dialog**. Instantly opens the prompt dialog to test countdown and options. |
| **[`stop_scheduled_tracker.bat`](stop_scheduled_tracker.bat)** | **Stops the Background Daemon**. Safely terminates any running scheduler processes. |

---

## 💻 CLI Usage

Direct command-line execution for advanced operations:

```bash
# 1. Parallel collection for all currently due items (Default: all attached emulators)
python run_collector.py --due --target-tab both

# 2. Collect a specific watchlist tier (e.g., Tier 1 Ultra-High)
python run_collector.py --tier 1 --pages 2 --target-tab both

# 3. Query a single specific item across 5 pages
python run_collector.py --query "突襲額外獎勵票券" --pages 5 --target-tab both

# 4. Limit parallel concurrency to 2 workers
python run_collector.py --due --parallel 2

# 5. Run aggregation & regenerate dashboard manually
python -m src.aggregator
python dashboard.py
```

---

## 📁 Repository Structure

```
artale_market_tracker/
├── assets/
│   ├── ADBKeyboard.apk        # Android unicode input IME helper
│   ├── favicon.png            # Dashboard favicon
│   └── icon.png               # Artale icon asset
├── data/
│   ├── backups/               # Automated timestamped SQLite backups
│   ├── market.db              # SQLite WAL database (trades, listings, candles)
│   └── quota_tracker.json     # Daily emulator search quota state
├── docs/
│   └── index.html             # Public GitHub Pages production dashboard
├── src/
│   ├── adb_controller.py      # Direct ADB device driver, screencap, & Unicode input
│   ├── parallel_collector.py  # Thread-safe multi-worker task split engine
│   ├── collector.py           # Core auction house scraping pipeline
│   ├── aggregator.py          # OHLCV candlestick aggregation engine
│   ├── tier_evaluator.py      # Trading velocity evaluator & tier categorizer
│   ├── database.py            # SQLite WAL connection manager & models
│   ├── ocr_engine.py          # Fast OCR preprocessing and text recognition
│   └── parser.py              # Auction UI layout slicers & pagination OCR
├── dashboard.py               # Generates Binance-style HTML dashboard
├── items_watchlist.json       # 105 tracked items with tier intervals & timestamps
├── run_collector.py           # Unified CLI interface
├── run_auto.ps1               # Automated end-to-end collection, aggregation & git sync
├── schedule_prompt_daemon.ps1 # Hourly WPF scheduler daemon
├── start_scheduled_tracker.bat
├── stop_scheduled_tracker.bat
├── run_auto.bat
└── run_collector_now.bat
```

---

## 📊 Live Production Dashboard

The live interactive dashboard is hosted on GitHub Pages:  
👉 **[https://gary1346aa.github.io/artale-market-dashboard/](https://gary1346aa.github.io/artale-market-dashboard/)**
