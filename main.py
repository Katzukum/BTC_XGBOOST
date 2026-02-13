
import threading
import time
import sys
import os

# Ensure project root is in path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.database import DatabaseManager
from src.ingestion import BinanceIngestor
from src.hyperliquid_ingestor import HyperLiquidIngestor

def start_ingestion_service(source: str = "BINANCE", drop_tables: bool = False, limit: int = 2000):
    """
    Initializes and starts the ingestion service (WebSocket + DB).
    Returns the active ingestor instance.
    """
    # Configuration
    DATA_SOURCE = source.upper() # Options: "BINANCE", "HYPERLIQUID"
    
    # Symbol mapping
    if DATA_SOURCE == "BINANCE":
        SYMBOL = "BTCUSDT"
    else:
        SYMBOL = "BTC" 
        
    HISTORY_INTERVALS = ["1m", "3m", "5m", "15m"]
    STREAM_INTERVAL = "1m"
    DB_PATH = "ohlcv.db"

    # Initialize Database
    print("Initializing Database...")
    db_manager = DatabaseManager(DB_PATH)
    
    if drop_tables:
        print("!!! Dropping Tables for Clean Fetch !!!")
        db_manager.drop_tables()

    # Initialize Ingestion
    print(f"Initializing Ingestion for {DATA_SOURCE}...")
    if DATA_SOURCE == "BINANCE":
        ingestor = BinanceIngestor(db_manager)
    else:
        ingestor = HyperLiquidIngestor(db_manager)

    # 1. Fetch History for ALL timeframes (Option A)
    for interval in HISTORY_INTERVALS:
        print(f"--- Fetching History for {SYMBOL} {interval} (Limit: {limit}) ---")
        try:
            ingestor.fetch_history(SYMBOL, interval, limit=limit)
        except Exception as e:
            print(f"Failed to fetch history for {interval}: {e}")

    # 2. Start WebSocket Stream ONLY for 1m
    print(f"\n--- Starting Stream for {SYMBOL} {STREAM_INTERVAL} ---")
    try:
        ingestor.start_stream(SYMBOL, STREAM_INTERVAL)
    except Exception as e:
        print(f"Failed to start stream: {e}")
        
    return ingestor

if __name__ == "__main__":
    ingestor = start_ingestion_service()
    
    print("\nSystem running (Aggregating 1m -> 3m, 5m, 15m). Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        ingestor.stop()
        print("Shutdown complete.")
