
import time
import json
import sys
import os
from datetime import datetime, timezone, timedelta
try:
    from zoneinfo import ZoneInfo
except ImportError:
    # Fallback for older python or if zoneinfo not installed, though 3.12 has it.
    # We can use a fixed offset for EST (UTC-5) but ZoneInfo is better for DST.
    # User is on 3.12 so ZoneInfo is available.
    pass

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Handle Model-XGBoost import
model_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Model-XGBoost')
sys.path.append(model_dir)

from src.polymarket import PolymarketClient
from src.tracker import TradeTracker
from predict import Predictor
from main import start_ingestion_service

def get_current_5_min_epoch():
    """
    Calculates the Unix timestamp for the START of the CURRENT 5-minute window.
    It rounds down to the nearest 5 minutes.
    """
    now = datetime.now(timezone.utc)
    remainder = now.minute % 5
    current_epoch_time = now.replace(minute=now.minute - remainder, second=0, microsecond=0)
    return int(current_epoch_time.timestamp())

def to_est(dt):
    """Converts a UTC datetime to EST (America/New_York)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZoneInfo("America/New_York"))


def main():
    print("--- FORWARD TESTER STARTED ---")
    
    pm = PolymarketClient()
    tracker = TradeTracker()
    
    print("Starting Ingestion Service...")
    try:
        ingestor = start_ingestion_service()
    except Exception as e:
        print(f"Failed to start ingestion: {e}")
        return

    # Allow ingestion to initialize
    time.sleep(5)
    
    print("Initializing Predictor...")
    try:
        predictor = Predictor() # Loads model
    except Exception as e:
        print(f"Failed to load predictor: {e}")
        return
    
    print("Systems initialized. Loop starting...")
    
    while True:
        try:
            # 1. Check Open Trades for Resolution
            # open_trades = tracker.get_open_trades()
            # if open_trades:
            #     # open_trades is list of (id, slug)
            #     print(f"Checking {len(open_trades)} open trades...")
            #     for trade_id, slug in open_trades:
            #         # Check status
            #         print(f"Checking status for {slug}...")
            #         winner = pm.get_market_resolution(trade_id)
            #         if winner:
            #            print(f" >> Trade {slug} RESOLVED: {winner}")
            #            # Update result (PnL 0 for now as we don't track amount)
            #            tracker.update_result(trade_id, winner, 0)
            
            # 2. Find Next Market (by Slug)
            epoch = get_current_5_min_epoch()
            slug = f"btc-updown-5m-{epoch}"
            
            # Print current time in EST
            now_est = to_est(datetime.now(timezone.utc))
            print(f"Current EST Time : {now_est.strftime('%Y-%m-%d %H:%M:%S %Z')}")
            print(f"Looking for Slug : {slug}")

            market = pm.get_market_by_slug(slug)
            if market:
                # Use the integer ID for API calls, not conditionId
                mid = market['id']
                mid = market['id']
                # slug is already known
                end_date_str = market['endDate']
                end_date_dt = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                end_date_est = to_est(end_date_dt)
                
                print(f" >> Market Found! Closes: {end_date_est.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                question = market['question']
                
                # Check if we already traded this
                # (Tracker should enforce unique ID)
                
                # Run Prediction
                # We need to ensure we are timely. 
                # If market starts in < 1 min, maybe too late?
                # or if it started already?
                
                 # Simple logic: Always predict latest candle.
                pred = predictor.predict_latest()
                if pred:
                    prob = pred['prob_up']
                    side = "UP" if prob > 0.5 else "DOWN"
                    confidence = prob if side == "UP" else (1.0 - prob)
                    
                    # Extract Price
                    try:
                        prices = json.loads(market.get('outcomePrices', '["0", "0"]'))
                        # prices[0] is usually "Yes" (UP)?, prices[1] is "No" (DOWN)?
                        # Polymarket outcome order: ["Yes", "No"] usually.
                        # Up = Yes, Down = No.
                        # Let's verify outcomes list just in case.
                        outcomes = json.loads(market.get('outcomes', '["Yes", "No"]'))
                        
                        price = 0.5 # fallback
                        if side == "UP":
                            if "Yes" in outcomes:
                                idx = outcomes.index("Yes")
                                price = float(prices[idx])
                        else:
                            if "No" in outcomes:
                                idx = outcomes.index("No")
                                price = float(prices[idx])
                                
                    except Exception as e:
                        print(f"Error parsing price: {e}")
                        price = 0.5 # fallback
                    
                    from colorama import Fore, Style, init
                    init(autoreset=True)

                    color = Fore.GREEN if side == "UP" else Fore.RED
                    print(f" >> Market: {question}")
                    print(f" >> Prediction: {color}{side}{Style.RESET_ALL} (Confidence: {confidence:.2%}) \n [Prob UP: {prob:.4f}] [Price: {price:.2f}]")

                    # Log if high conviction? Or logging all for data?
                    # Let's log all for forward testing analysis.
                    
                    tracker.log_trade(
                        market_id=mid,
                        slug=slug,
                        question=question,
                        end_date=end_date_str,
                        side=side,
                        prob=float(prob),
                        entry_price=float(price)
                    )
            
            else:
                print("No suitable market found.")
                
            time.sleep(30)
            
        except Exception as e:
            print(f"Error in loop: {e}")
            time.sleep(30)
        except KeyboardInterrupt:
            print("\nStopping Forward Tester...")
            break
    
    if 'ingestor' in locals():
        print("Stopping Ingestion Service...")
        ingestor.stop()
    print("Shutdown Complete.")

if __name__ == "__main__":
    main()
