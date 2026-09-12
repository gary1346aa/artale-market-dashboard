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

## Directory Structure

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
