import os
import sys
import eel
import threading
import time
import logging
import json
from datetime import datetime, timezone
try:
    from zoneinfo import ZoneInfo
except ImportError:
    pass # fallback handled if needed

# Ensure src and Model_XGBoost are in path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "Model_XGBoost"))

from src.dashboard_service import DashboardService
from src.database import DatabaseManager
from src.tracker import TradeTracker
from src.ingestion import BinanceIngestor
from src.hyperliquid_ingestor import HyperLiquidIngestor
from src.auditor import TradeAuditor
from src.polymarket import PolymarketClient
from predict import Predictor 

# --- Configuration ---
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
WEB_ROOT = os.path.join(PROJECT_ROOT, "web")

# Global State
latest_predictions = {
    "BINANCE": None,
    "HYPERLIQUID": None
}
ingestion_running = False
active_contract = None

# Control Flags
ENABLE_BINANCE = True
ENABLE_HYPERLIQUID = True
ENABLE_SIM_TRADING = True

# Services (Initialized in main)
db_manager = None
tracker = None
service = None
binance_ingestor = None
hl_ingestor = None
binance_predictor = None
hl_predictor = None
auditor = None
polymarket = None

@eel.expose
def get_dashboard_snapshot(timeframe="1m", source="BINANCE"):
    if service:
        snapshot = service.get_snapshot(timeframe=timeframe, source=source, predictions=latest_predictions)
        
        # Inject Active Contract & Edge
        if active_contract:
            snapshot['active_contract'] = active_contract
            
            # Calculate Edge
            edge_data = calculate_edge_and_kelly(active_contract, latest_predictions)
            
            # Update Pipeline Display
            # Snapshot pipeline is a dict: { 'edge': '...', 'kelly': '...', ... }
            if snapshot.get('execution_pipeline'):
                 snapshot['execution_pipeline']['edge'] = edge_data['edge']
                 snapshot['execution_pipeline']['kelly'] = edge_data['kelly']
                 snapshot['execution_pipeline']['exec'] = edge_data['ev']

        return snapshot
    return {}

@eel.expose
def update_controls(data):
    """
    Called from frontend to update global control flags.
    data = { 'binance': bool, 'hyperliquid': bool, 'sim': bool }
    """
    global ENABLE_BINANCE, ENABLE_HYPERLIQUID, ENABLE_SIM_TRADING
    print(f"Updated Controls: {data}")
    ENABLE_BINANCE = data.get('binance', True)
    ENABLE_HYPERLIQUID = data.get('hyperliquid', True)
    ENABLE_SIM_TRADING = data.get('sim', True)
    return {"status": "ok"}


@eel.expose
def ping():
    return {"status": "ok"}


def get_current_5_min_epoch():
    """Calculates the Unix timestamp for the START of the current 5-minute window."""
    now = datetime.now(timezone.utc)
    remainder = now.minute % 5
    current_epoch_time = now.replace(minute=now.minute - remainder, second=0, microsecond=0)
    return int(current_epoch_time.timestamp())


def audit_worker():
    """Background thread to check for expired trades and update PnL."""
    global active_contract
    print("--- Audit & Contract Worker Started ---")
    
    # Initial fetch
    try:
        if polymarket:
            print("Fetching initial contract...")
            active_contract = polymarket.find_next_btc_5m_market()
            if active_contract:
                print(f"Active Contract Found: {active_contract.get('slug')}")
    except Exception as e:
        print(f"Initial Contract Fetch Error: {e}")

    last_audit_time = 0
    
    while True:
        try:
            now = time.time()
            
            # 1. Audit Trades (Every 60s)
            if now - last_audit_time > 60:
                if auditor:
                    auditor.resolve_expired_trades()
                
                last_audit_time = now

        except Exception as e:
            print(f"Audit Error: {e}")
        
        time.sleep(1) 


def calculate_edge_and_kelly(contract, predictions):
    """
    Calculates Edge and Kelly Criterion based on contract prices and model predictions.
    Edge = (Model Prob - Market Price)
    Kelly = Edge / (1 - Market Price) (if Edge > 0)
    
    Returns:
        {
            "edge": str,   # Display string e.g. "Edge +5.2%"
            "kelly": str,  # Display string e.g. "Kelly 12%"
            "raw_edge": float,
            "direction": str # "UP" or "DOWN"
        }
    """
    default_res = {"edge": "Edge --", "kelly": "Kelly --", "ev": "EV --", "raw_edge": 0.0, "direction": "NONE"}
    
    if not contract or not predictions:
        return default_res

    # 1. Get Market Prices
    try:
        prices = contract.get('outcomePrices', [])
        if isinstance(prices, str):
            prices = json.loads(prices)
        prices = [float(p) for p in prices]
        if len(prices) < 2:
            return default_res
        market_prob_up = prices[0]
        market_prob_down = prices[1]
    except Exception as e:
        print(f"Error parsing contract prices: {e}")
        return default_res

    # 2. Calculate Individual and Combined Edges
    edges_list = []
    probs_up = []
    
    # Helper to calculate best edge for a given prob_up
    def get_best_edge(prob_up, price_up, price_down):
        prob_down = 1.0 - prob_up
        
        # Edge = Prob - Price
        edge_up = prob_up - price_up
        edge_down = prob_down - price_down
        
        # Pick the "best" edge (arithmetically highest)
        # Usually implies the trade we want to take.
        # If both are negative, we pick the least negative? Or just show the one closer to positive?
        # Let's show the max.
        
        if edge_up >= edge_down:
            return {"side": "UP", "value": edge_up}
        else:
            # If down is better
            return {"side": "DN", "value": edge_down}

    sources = ["BINANCE", "HYPERLIQUID"]
    for src in sources:
        if predictions.get(src):
            try:
                p_up = float(predictions[src]["prob_up"])
                probs_up.append(p_up)
                
                best = get_best_edge(p_up, market_prob_up, market_prob_down)
                
                edges_list.append({
                    "source": src,
                    "value": best["value"],
                    "side": best["side"]
                })
            except Exception:
                pass
                
    if not probs_up:
        return default_res
        
    # Average Edge (Composite)
    avg_prob_up = sum(probs_up) / len(probs_up)
    best_cmb = get_best_edge(avg_prob_up, market_prob_up, market_prob_down)
    combined_edge_val = best_cmb["value"]
    
    # Add Combined to list (at the end)
    edges_list.append({
        "source": "CMB",
        "value": combined_edge_val,
        "side": best_cmb["side"]
    })

    # 3. Calculate Kelly (Based on Combined Edge)
    # Kelly = Edge / (1 - Price_of_Trade)
    # Use the Best Combined Edge
    
    market_price = market_prob_up if best_cmb["side"] == "UP" else market_prob_down
    
    kelly = 0.0
    if combined_edge_val > 0 and market_price < 1.0:
        kelly = combined_edge_val / (1.0 - market_price)
            
    kelly_str = f"Kelly {kelly*100:.1f}%"
    
    # Calculate EV (Expected Value)
    # EV = Edge * Number_of_Contracts
    # User specified min bet = 5 contracts.
    # Edge is Profit per contract (Prob * $1 - Price).
    
    num_contracts = 5.0
    ev_val = combined_edge_val * num_contracts
    ev_str = f"EV ${ev_val:+.2f}"
    
    return {
        "edge": edges_list, # App.js handles this array
        "kelly": kelly_str,
        "ev": ev_str,
        "raw_edge": combined_edge_val,
        "direction": best_cmb["side"]
    }

def price_worker():
    """Fetches Polymerket prices every 1s."""
    global active_contract
    print("--- Price Worker Started ---")
    while True:
        try:
            if active_contract and polymarket:
                # Enrich with live CLOB prices
                active_contract = polymarket.enrich_market_with_prices(active_contract)
        except Exception as e:
            print(f"Price Worker Error: {e}")
        time.sleep(1)

def contract_worker():
    """
    Checks for new Active Contract every 5s.
    Only updates global state if the contract has changed (SLUG check).
    """
    global active_contract
    print("--- Contract Worker Started ---")
    
    # Initial Fetch
    try:
        if polymarket:
            print("Fetching initial contract...")
            new_c = polymarket.find_next_btc_5m_market()
            if new_c:
                active_contract = new_c
                print(f"Active Contract Found: {active_contract.get('slug')}")
    except Exception as e:
        print(f"Initial Contract Error: {e}")

    while True:
        try:
            if polymarket:
                new_c = polymarket.find_next_btc_5m_market()
                if new_c:
                    # Check if duplicated call / same contract
                    current_slug = active_contract.get('slug') if active_contract else None
                    new_slug = new_c.get('slug')
                    
                    if new_slug != current_slug:
                        print(f"Contract Worker: Switching to {new_slug}")
                        active_contract = new_c
                    # else: Keep existing active_contract (preserves live prices from price_worker)

        except Exception as e:
            print(f"Contract Worker Error: {e}")
            
        time.sleep(5)

def strategy_worker():
    """
    High-Frequency Strategy Loop (0.5s).
    Handles Entry, Stop Loss, and Take Profit.
    """
    global latest_predictions, active_contract
    print("--- Strategy Worker Started ---")
    
    while True:
        try:
            if not ENABLE_SIM_TRADING:
                time.sleep(1)
                continue

            # --- 1. GET DATA ---
            # Predictions
            pred_bin = latest_predictions.get("BINANCE")
            pred_hl = latest_predictions.get("HYPERLIQUID")
            
            if not pred_bin or not pred_hl:
                time.sleep(0.5)
                continue
                
            try:
                prob_bin = float(pred_bin['prob_up'])
                prob_hl = float(pred_hl['prob_up'])
                avg_prob = (prob_bin + prob_hl) / 2.0
            except:
                time.sleep(0.5)
                continue
                
            # Contract Prices
            if not active_contract:
                time.sleep(0.5)
                continue
                
            prices = active_contract.get('outcomePrices', [])
            if isinstance(prices, str):
                import json
                prices = json.loads(prices)
            
            if len(prices) < 2:
                time.sleep(0.5)
                continue
                
            try:
                price_up = float(prices[0])
                price_down = float(prices[1])
            except:
                time.sleep(0.5)
                continue

            # --- 2. MANAGE OPEN TRADES (SL / TP) ---
            open_trades = tracker.get_open_trades()
            
            for trade in open_trades:
                tid = trade['id']
                side = trade['prediction_side']
                entry_price = trade['entry_price']
                tp_price = trade.get('profit_target')
                
                # Check based on current market data
                # Identify if this trade belongs to the current active contract or another
                # If it's a different contract, we might not have live prices for it here easily if active_contract is different.
                # Limitation: We only track active_contract prices. 
                # Assumption: Valid trades are only on active_contract.
                
                if trade['market_slug'] != active_contract.get('slug'):
                    continue # Cannot manage if not active (will be handled by auditor expiry)
                    
                current_price = price_up if side == "UP" else price_down
                
                # Check STOP LOSS (Model Confidence Lost)
                # SL: Avg Odds < 65% (for UP) or > 35% (for DOWN) -> IMPLIED by "No longer avg above 65%"
                sl_triggered = False
                if side == "UP" and avg_prob < 0.65:
                    sl_triggered = True
                elif side == "DOWN" and avg_prob > 0.35:
                    sl_triggered = True
                    
                if sl_triggered:
                    # CLOSE TRADE (SL)
                    payout = current_price # You sell at current price
                    pnl = payout - entry_price
                    tracker.close_trade(tid, pnl, "SL_ODDS_DROP")
                    continue # Trade closed, next
                    
                # Check TAKE PROFIT
                if tp_price and current_price >= tp_price:
                    # CLOSE TRADE (TP)
                    pnl = current_price - entry_price
                    tracker.close_trade(tid, pnl, "TP_HIT")
                    continue

            # --- 3. CHECK FOR NEW ENTRY ---
            # Only enter if no open trade for this contract
            # We filter open_trades for current slug
            existing_trade = next((t for t in open_trades if t['market_slug'] == active_contract.get('slug')), None)
            
            if not existing_trade:
                # ENTRY LOGIC
                # 1. Avg Odds > 65% (UP) or < 35% (DOWN)
                # 2. CMB Edge > 5%
                
                signal_side = None
                confidence = 0.0
                market_price = 0.0
                
                if avg_prob > 0.65:
                    # Potential UP
                    edge = avg_prob - price_up
                    if edge > 0.05:
                        signal_side = "UP"
                        confidence = avg_prob
                        market_price = price_up
                        edge_val = edge
                elif avg_prob < 0.35:
                    # Potential DOWN
                    # Edge for DOWN = Prob(Down) - Price(Down)
                    # Prob(Down) = 1 - avg_prob
                    prob_down = 1.0 - avg_prob
                    edge = prob_down - price_down
                    if edge > 0.05:
                        signal_side = "DOWN"
                        confidence = MIN_CONF = avg_prob # Store raw prob? Or concept confidence?
                        # Tracker expects "prediction_prob". If DOWN, usually we store 0.3 or 0.7?
                        # Logic in tracker: "prediction_side" stores UP/DOWN. "prediction_prob" usually stores the model output (0-1).
                        confidence = avg_prob 
                        market_price = price_down
                        edge_val = edge

                if signal_side:
                    # Calculate EV and Profit Target
                    # EV = Edge * Contracts (5)
                    # Profit Target = Entry + (EV / 5) = Entry + Edge
                    # Wait, Prompt said: "profit target of the entry + (EV/5)"
                    # EV = Edge * 5
                    # Target = Entry + (Edge * 5) / 5 = Entry + Edge.
                    # So Target = Entry + Edge = Model_Probability.
                    # Example: Prob 0.70, Price 0.60. Edge 0.10.
                    # EV = 0.50 (for 5 shares).
                    # Target = 0.60 + 0.10 = 0.70.
                    # Makes sense: Target is the "Fair Value" (Model Prob).
                    
                    target = market_price + (edge_val/2)
                    
                    # Log Trade
                    slug = active_contract.get('slug')
                    question = f"BTC {signal_side} {confidence:.2f}"
                    epoch = get_current_5_min_epoch() # Approximate
                    end_date_dt = datetime.fromtimestamp(epoch + 300, tz=timezone.utc)
                    end_date_str = end_date_dt.strftime('%Y-%m-%dT%H:%M:%SZ') # Approx
                    
                    tracker.log_trade(
                        market_id=slug, # Sim ID
                        slug=slug,
                        question=question,
                        end_date=end_date_str,
                        side=signal_side,
                        prob=confidence,
                        entry_price=market_price,
                        profit_target=target
                    )
                    
        except Exception as e:
            print(f"Strategy Worker Error: {e}")
            
        time.sleep(0.5)

def check_and_log_consensus():
    """
    Deprecated: Entry logic moved to strategy_worker.
    Kept as empty placeholder if needed or to remove completely.
    """
    pass


def background_worker():
    global ingestion_running, latest_predictions
    
    print("--- Background Worker Started ---")
    
    # 1. Fetch History
    print("Fetching History...")
    intervals = ["1m", "3m", "5m", "15m"]
    try:
        for interval in intervals:
            limit = 500 if interval == "1m" else 100 
            if ENABLE_BINANCE:
                binance_ingestor.fetch_history("BTCUSDT", interval, limit=limit)
            if ENABLE_HYPERLIQUID:
                hl_ingestor.fetch_history("BTC", interval, limit=limit)
    except Exception as e:
        print(f"Error fetching history: {e}")

    # 2. Start Streams
    print("Starting Streams...")
    try:
        if ENABLE_BINANCE:
            binance_ingestor.start_stream("BTCUSDT", "1m")
        if ENABLE_HYPERLIQUID:
            hl_ingestor.start_stream("BTC", "1m")
    except Exception as e:
        print(f"Error starting streams: {e}")

    ingestion_running = True
    
    # 3. Prediction Loop
    print("Starting Prediction Loop...")
    while True:
        try:
            # --- BINANCE ---
            if ENABLE_BINANCE:
                try:
                    pred_bin = binance_predictor.predict_latest()
                    if pred_bin:
                        pred_bin['prob_up'] = float(pred_bin['prob_up'])
                        latest_predictions["BINANCE"] = pred_bin
                except Exception as e:
                    print(f"Binance Predict Error: {e}")
            else:
                latest_predictions["BINANCE"] = None

            # --- HYPERLIQUID ---
            if ENABLE_HYPERLIQUID:
                try:
                    pred_hl = hl_predictor.predict_latest()
                    if pred_hl:
                        pred_hl['prob_up'] = float(pred_hl['prob_up'])
                        latest_predictions["HYPERLIQUID"] = pred_hl
                except Exception as e:
                    print(f"Hyperliquid Predict Error: {e}")
            else:
                latest_predictions["HYPERLIQUID"] = None
                
            # --- CONSENSUS & LOGGING ---
            if ENABLE_SIM_TRADING:
                check_and_log_consensus()
                
        except Exception as e:
            print(f"Loop Error: {e}")
        
        time.sleep(3)


def main():
    global db_manager, tracker, service
    global binance_ingestor, hl_ingestor
    global binance_predictor, hl_predictor
    global auditor, polymarket

    # Init Core Services
    db_manager = DatabaseManager("ohlcv.db")
    tracker = TradeTracker("trades.db")
    service = DashboardService(PROJECT_ROOT)
    auditor = TradeAuditor("trades.db")
    polymarket = PolymarketClient()

    # Init Ingestors (Shared DB)
    binance_ingestor = BinanceIngestor(db_manager)
    hl_ingestor = HyperLiquidIngestor(db_manager)

    # Init Predictors
    try:
        binance_predictor = Predictor(source="binance")
        hl_predictor = Predictor(source="hyperliquid")
    except Exception as e:
        print(f"Failed to load predictors: {e}")
        return

    # Start Background Threads
    t_ingest = threading.Thread(target=background_worker, daemon=True)
    t_ingest.start()
    
    t_audit = threading.Thread(target=audit_worker, daemon=True)
    t_audit.start()
    
    t_price = threading.Thread(target=price_worker, daemon=True)
    t_price.start()

    t_contract = threading.Thread(target=contract_worker, daemon=True)
    t_contract.start()
    
    t_strategy = threading.Thread(target=strategy_worker, daemon=True)
    t_strategy.start()

    # Start UI
    eel.init(WEB_ROOT)
    port = int(os.environ.get("EEL_PORT", "8080"))
    mode = os.environ.get("EEL_MODE", "chrome")
    eel.start("index.html", size=(1600, 980), port=port, mode=mode)


if __name__ == "__main__":
    try:
        main()
    except (SystemExit, KeyboardInterrupt):
        sys.exit(0)

