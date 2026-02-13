# BTC-XGBoost Trading Bot

## Overview
This project uses an XGBoost model to predict BTC price movements on Polymarket (5-minute intervals).

## Setup
1. Install dependencies: `uv sync`
2. Activate virtual environment: `.venv\Scripts\activate` (Windows) or `source .venv/bin/activate` (Linux/macOS)

## Usage

### Run Live/Forward Test
```bash
python forward_test.py
```

### Run Eel Realtime Dashboard
Starts a dark-themed desktop dashboard that displays live BTC market data, prediction signals, execution pipeline context, and trade performance logs.

```bash
python eel_app.py
```

Environment variables:
- `EEL_PORT` (default: `8080`)
- `EEL_MODE` (`chrome`, `edge`, or `default`; default: `chrome`)

### Audit Trade Performance
Analyze historical trade performance from `trades.db`.
```bash
python audit_trades.py
```

## Structure
- `src/`: Core logic (tracker, polymarket client, ingestion, dashboard service).
- `web/`: Eel frontend files (HTML/CSS/JS realtime dashboard).
- `Model-XGBoost/`: Model training and prediction logic.
- `trades.db`: SQLite database storing trade history.
