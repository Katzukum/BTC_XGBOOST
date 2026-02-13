
import sqlite3
import os
from datetime import datetime, timezone

class TradeTracker:
    def __init__(self, db_path="trades.db"):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS forward_trades (
                id TEXT PRIMARY KEY,
                market_slug TEXT,
                question TEXT,
                end_date TEXT,
                prediction_side TEXT,
                prediction_prob REAL,
                entry_time TEXT,
                status TEXT DEFAULT 'OPEN',
                result_side TEXT,
                pnl REAL,
                entry_price REAL
            )
        ''')
        
        # Check if entry_price exists, if not add it
        try:
            c.execute("SELECT entry_price FROM forward_trades LIMIT 1")
        except sqlite3.OperationalError:
            print("Migrating DB: Adding entry_price column...")
            c.execute("ALTER TABLE forward_trades ADD COLUMN entry_price REAL")
            
        conn.commit()
        conn.close()

    def log_trade(self, market_id, slug, question, end_date, side, prob, entry_price=None):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            c.execute('''
                INSERT INTO forward_trades (id, market_slug, question, end_date, prediction_side, prediction_prob, entry_price, entry_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (market_id, slug, question, end_date, side, prob, entry_price, datetime.now(timezone.utc).isoformat()))
            conn.commit()
            print(f"Logged trade: {side} on {slug} (Prob: {prob:.2f}, Price: {entry_price})")
        except sqlite3.IntegrityError:
            print(f"Trade {market_id} already logged.")
        finally:
            conn.close()

    def get_open_trades(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT id, market_slug FROM forward_trades WHERE status='OPEN'")
        rows = c.fetchall()
        conn.close()
        return rows

    def update_result(self, market_id, result_side, pnl):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''
            UPDATE forward_trades
            SET status='CLOSED', result_side=?, pnl=?
            WHERE id=?
        ''', (result_side, pnl, market_id))
        conn.commit()
        conn.close()
        print(f"Updated trade {market_id}: Result {result_side}, PnL {pnl}")
