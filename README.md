# Artale Market Analysis & Stock Tracking System

A market monitoring, OCR extraction, and price analytics pipeline for **MapleStory Worlds - Artale**.

## Features & Core Modules

1. **Dual Market Tracking**:
   - **Sell Price / Active Listings (`查詢` Section)**: Captures active asks, order book depth, lowest prices, quantities, and seller IDs.
   - **Match Price / Transaction History (`市價` Section)**: Captures actual completed transaction prices, true trading volumes, and historical execution trends.

2. **Computer Vision & OCR Engine**:
   - High-speed native Windows Media OCR (`winocr`) supporting Traditional Chinese (`zh-Hant-TW`) and numeric data.
   - ROI (Region of Interest) coordinate segmentation for multi-row tabular extraction.
   - Image preprocessing (scaling, thresholding, denoising) optimized for pixel-art fonts.

3. **Storage & Financial Analytics**:
   - SQLite / PostgreSQL time-series schema.
   - Volume-Weighted Average Price (VWAP), Simple Moving Averages (SMA), and anomaly / mispricing detection.

## Running Data Collection

The system supports two collection modes:

### 1. Passive Mode (Zero Anti-Cheat Risk, Recommended)
Run in the background while you play or browse the Artale market manually:
```bash
python run_collector.py --mode passive
```
- **`[F9]`**: Press anytime to capture the active market page (auto-detects `[查詢]` vs `[市價]` tab and saves all rows to SQLite).
- **`[F10]`**: Toggle continuous background watcher (records whenever you browse pages).

### 2. Auto Collection Mode
Navigates the market UI, types search queries, flips pages, and captures both tabs:
```bash
# Single search item
python run_collector.py --mode auto --query "頭盔" --pages 2

# Full catalog scan using watchlist
python run_collector.py --mode auto --watchlist items_watchlist.json --pages 2
```

> [!NOTE]
> Moving your mouse quickly to any corner of the screen triggers the PyAutoGUI emergency fail-safe and immediately stops the automated collector.

```
artale_market_tracker/
├── src/
│   ├── __init__.py
│   ├── models.py          # Data models for active listings and matched trades
│   ├── database.py        # SQLite persistence layer
│   ├── ocr_engine.py      # Preprocessing and Windows OCR wrappers
│   └── parser.py          # Tabular ROI slicers for 查詢 and 市價 views
├── tests/
│   └── test_parser.py     # Unit test against UI screenshots
├── requirements.txt
└── README.md
```
