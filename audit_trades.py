import sqlite3
import pandas as pd
from datetime import datetime, timezone, timedelta
import time
import sys
import os

# Add src to path if needed, though running from root should work
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from src.polymarket import PolymarketClient
from src.tracker import TradeTracker

class TradeAuditor:
    """Analyzes trade performance from the SQLite database."""

    def __init__(self, db_path: str = "trades.db"):
        self.db_path = db_path
        self.pm = PolymarketClient()
        self.tracker = TradeTracker(db_path=db_path)

    def resolve_expired_trades(self):
        """Checks and resolves expired trades."""
        print("\n--- CHECKING FOR EXPIRED TRADES ---")
        open_trades = self.tracker.get_open_trades()
        
        if not open_trades:
            print("No open trades to check.")
            return

        print(f"Found {len(open_trades)} open trades. Checking expiration...")
        
        # We need to get details (end_date) which are not in get_open_trades (only id, slug)
        # So we fetch all open trades from DB with details
        df = self.get_trades()
        if df.empty: return
        
        open_df = df[df['status'] == 'OPEN']
        
        now = datetime.now(timezone.utc)
        
        for _, row in open_df.iterrows():
            trade_id = row['id']
            slug = row['market_slug']
            end_date_str = row['end_date']
            side = row['prediction_side']
            side = row['prediction_side']
            prob = row['prediction_prob']
            entry_price = row.get('entry_price')
            
            # Decode prob if needed (handled by get_trades but let's be safe if using raw row)
            # Actually get_trades returns proper float now hopefully
            
            if not end_date_str:
                continue
                
            try:
                # Handle ISO format with Z
                end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
            except ValueError:
                print(f"Invalid date format for {slug}: {end_date_str}")
                continue
            
            # Check if expired (give 1 minute buffer)
            if now > end_date:
                print(f"Trade {slug} expired on {end_date}. Fetching resolution...")
                
                resolution = self.pm.get_market_resolution(trade_id)
                
                if resolution:
                    # resolution is usually "Yes" or "No" from our PolymarketClient
                    # Map to UP/DOWN
                    # Typically Yes = UP, No = DOWN for "Will BTC be > X?"
                    # We should confirm this mapping.
                    # existing code says: outcome = t.get('outcome') # "Yes" or "No"
                    
                    won = False
                    if resolution == "Yes" and side == "UP":
                        won = True
                    elif resolution == "No" and side == "DOWN":
                        won = True
                    
                    # Calculate PnL
                    # Cost basis: 
                    # Use entry_price if available, else fallback to prob/1-prob
                    if entry_price is not None and entry_price > 0:
                        cost = entry_price
                    else:
                        cost = prob if side == "UP" else (1.0 - prob)
                    
                    # Payout = 1 if Won else 0
                    payout = 1.0 if won else 0.0
                    
                    pnl = payout - cost
                    
                    print(f" -> Resolved: {resolution}. Prediction: {side}. PnL: {pnl:.4f}")
                    
                    # Update DB
                    # We need to pass 'UP' or 'DOWN' to update_result?
                    # tracker.update_result args: market_id, result_side, pnl
                    # result_side should probably be the resolution (Yes/No) or mapped
                    self.tracker.update_result(market_id=trade_id, result_side=resolution, pnl=pnl)
                else:
                    print(f" -> Market not yet resolved via API.")
            else:
                # Not expired
                pass

    def get_trades(self) -> pd.DataFrame:
        """Fetches all trades from the database and cleans data."""
        try:
            conn = sqlite3.connect(self.db_path)
            query = "SELECT * FROM forward_trades"
            df = pd.read_sql_query(query, conn)
            conn.close()
            
            # Fix for legacy binary data in prediction_prob
            def decode_prob(val):
                if isinstance(val, bytes):
                    import struct
                    try:
                        return struct.unpack('<f', val)[0]
                    except:
                        return 0.0
                return val

            if 'prediction_prob' in df.columns and not df.empty:
                df['prediction_prob'] = df['prediction_prob'].apply(decode_prob)
                
            return df
        except sqlite3.OperationalError:
            print(f"Error: Could not find table 'forward_trades' in {self.db_path}. Is the database initialized?")
            return pd.DataFrame()
        except Exception as e:
            print(f"Error reading database: {e}")
            return pd.DataFrame()

    def analyze_performance(self):
        """Calculates and prints performance metrics."""
        df = self.get_trades()

        if df.empty:
            print("No trades found in database.")
            return

        # Separate Open and Closed Trades
        open_trades = df[df['status'] == 'OPEN']
        closed_trades = df[df['status'] == 'CLOSED']

        print(f"\n{'='*40}")
        print(f"TRADE AUDIT REPORT - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*40}\n")

        print(f"Total Trades Logged: {len(df)}")
        print(f"Open Trades:         {len(open_trades)}")
        print(f"Closed Trades:       {len(closed_trades)}")

        if not closed_trades.empty:
            # Ensure PnL is numeric
            closed_trades.loc[:, 'pnl'] = pd.to_numeric(closed_trades['pnl'], errors='coerce').fillna(0.0)

            total_pnl = closed_trades['pnl'].sum()
            avg_pnl = closed_trades['pnl'].mean()
            
            # Win Rate Calculation
            # Assuming a win is PnL > 0. 
            winning_trades = closed_trades[closed_trades['pnl'] > 0]
            win_rate = (len(winning_trades) / len(closed_trades)) * 100

            # Best and Worst
            best_trade = closed_trades.loc[closed_trades['pnl'].idxmax()]
            worst_trade = closed_trades.loc[closed_trades['pnl'].idxmin()]

            print(f"\n--- PERFORMANCE (CLOSED TRADES) ---")
            print(f"Total PnL:           ${total_pnl:.2f}")
            print(f"Average PnL:         ${avg_pnl:.2f}")
            print(f"Win Rate:            {win_rate:.2f}% ({len(winning_trades)}/{len(closed_trades)})")
            print(f"Best Trade:          ${best_trade['pnl']:.2f} (ID: {best_trade['id']})")
            print(f"Worst Trade:         ${worst_trade['pnl']:.2f} (ID: {worst_trade['id']})")
            
            # Show recent closed trades
            print(f"\n--- RECENT CLOSED TRADES (Last 5) ---")
            print(closed_trades.tail(5)[['entry_time', 'market_slug', 'prediction_side', 'pnl']].to_string(index=False))

        if not open_trades.empty:
            print(f"\n--- ACTIVE TRADES ---")
            print(open_trades[['entry_time', 'market_slug', 'prediction_side', 'prediction_prob']].to_string(index=False))

        print(f"\n{'='*40}")

if __name__ == "__main__":
    while True:
        auditor = TradeAuditor()
        auditor.resolve_expired_trades()
        auditor.analyze_performance()
        #print a sleep meassage with the time of next run in EST (now+5 minutes)
        print(f"Next rerun in 5 minutes. Current EST Time : {(datetime.now()+timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S')} EST")
        time.sleep(300)
