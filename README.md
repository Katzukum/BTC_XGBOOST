# BTC-XGBoost Trading Bot

## Overview
This project uses an XGBoost model to predict BTC price movements on Polymarket (5-minute intervals).

## Setup
1. Install dependencies: `uv sync`
2. Activate virtual environment: `.venv\Scripts\activate`

## Usage

### Run Live/Forward Test
```bash
python forward_test.py
```

### Audit Trade Performance
Analyze historical trade performance from `trades.db`.
```bash
python audit_trades.py
```

## Structure
- `src/`: Core logic (tracker, polymarket client).
- `Model-XGBoost/`: Model training and prediction logic.
- `trades.db`: SQLite database storing trade history.
