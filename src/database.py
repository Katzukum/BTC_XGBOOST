
import sqlite3
import pandas as pd
from typing import List, Tuple, Optional, Dict, Any

class DatabaseManager:
    def __init__(self, db_path: str = "ohlcv.db"):
        self.db_path = db_path
        self.conn = None
        self.init_db()

    def init_db(self):
        """
        Initializes the database connection and tables.
        Enables WAL mode for concurrent reading/writing.
        """
        # Establish persistent connection
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row # Access columns by name
        
        cursor = self.conn.cursor()
        
        # Enable Write-Ahead Logging (WAL) for concurrency
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;") # Faster writes, slightly less safe on power loss but fine for cache
        
        # Create tables for each supported interval and source
        sources = ["binance", "hyperliquid"]
        intervals = ["1m", "3m", "5m", "15m"]
        
        for source in sources:
            for interval in intervals:
                table_name = f"{source}_ohlcv_{interval}"
                cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {table_name} (
                        timestamp INTEGER PRIMARY KEY,
                        open REAL,
                        high REAL,
                        low REAL,
                        close REAL,
                        volume REAL
                    )
                """)
        self.conn.commit()

    def drop_tables(self):
        """
        Drops all OHLCV tables to allow for a fresh start.
        """
        sources = ["binance", "hyperliquid"]
        intervals = ["1m", "3m", "5m", "15m"]
        
        cursor = self.conn.cursor()
        for source in sources:
            for interval in intervals:
                table_name = f"{source}_ohlcv_{interval}"
                cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
        self.conn.commit()
        print("All tables dropped.")
        
        # Re-initialize empty tables
        self.init_db()

    def insert_candle(self, source: str, symbol: str, interval: str, candle: Dict[str, Any]):
        """
        Inserts a single candle into the database for a specific source.
        Uses the persistent connection.
        """
        table_name = f"{source.lower()}_ohlcv_{interval}"
        try:
             cursor = self.conn.cursor()
             # Handle potential string/float inputs
             t = candle.get('t') or candle.get('timestamp')
             o = float(candle.get('o') or candle.get('open'))
             h = float(candle.get('h') or candle.get('high'))
             l = float(candle.get('l') or candle.get('low'))
             c = float(candle.get('c') or candle.get('close'))
             v = float(candle.get('v') or candle.get('volume'))

             cursor.execute(f"""
                INSERT OR REPLACE INTO {table_name} (timestamp, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?)
             """, (t, o, h, l, c, v))
             self.conn.commit()
        except Exception as e:
            print(f"DB Write Error: {e}")

    def get_candles(self, source: str, symbol: str, interval: str, limit: int = 100) -> pd.DataFrame:
        table_name = f"{source.lower()}_ohlcv_{interval}"
        try:
            query = f"""
                SELECT timestamp, open, high, low, close, volume
                FROM {table_name}
                ORDER BY timestamp DESC
                LIMIT ?
            """
            df = pd.read_sql_query(query, self.conn, params=(limit,))
            if not df.empty:
                df = df.sort_values('timestamp').reset_index(drop=True)
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except pd.errors.DatabaseError:
            return pd.DataFrame()
        except Exception as e:
            print(f"DB Read Error: {e}")
            return pd.DataFrame()

    def close(self):
        if self.conn:
            self.conn.close()
