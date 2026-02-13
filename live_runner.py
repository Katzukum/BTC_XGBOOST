
import sys
import time
import os
import signal
import threading
from colorama import init, Fore, Style

# Initialize colorama
init(autoreset=True)

# Add Model-XGBoost to path so we can import Predictor
sys.path.append(os.path.join(os.path.dirname(__file__), 'Model-XGBoost'))
from predict import Predictor

# Import ingestion starter
from main import start_ingestion_service

def main():
    print(Fore.CYAN + Style.BRIGHT + "--- STARTING LIVE SYSTEM (THREADED) ---")
    
    # CONFIGURATION
    DATA_SOURCE = "BINANCE" # Options: "BINANCE", "HYPERLIQUID"
    
    # 1. Start Ingestion Service (In same process)
    # The ingestor starts its own threads for WebSocket.
    print(Fore.YELLOW + "Launching Ingestion Service...")
    try:
        # Pass the source explicitly
        ingestor = start_ingestion_service(source=DATA_SOURCE)
    except Exception as e:
        print(Fore.RED + f"Failed to start ingestion: {e}")
        return

    # Allow ingestion to initialize
    time.sleep(5)
    
    # 2. Initialize Predictor
    print(Fore.YELLOW + "\nInitializing AI Model...")
    try:
        # Pass the source explicitly
        predictor = Predictor(source=DATA_SOURCE.lower())
    except Exception as e:
        print(Fore.RED + f"Failed to load model: {e}")
        if 'ingestor' in locals():
            ingestor.stop()
        return

    print(Fore.GREEN + Style.BRIGHT + "\n--- LIVE LOOP STARTED ---")
    print(Fore.CYAN + "Press Ctrl+C to stop.")

    try:
        while True:
            # Run prediction loop every X seconds
            
            try:
                result = predictor.predict_latest()
                
                if result:
                    ts = result['time']
                    prob = result['prob_up']
                    
                    # Colorize probability based on value
                    prob_color = Fore.WHITE
                    if prob > 0.6:
                        prob_color = Fore.GREEN
                    elif prob < 0.4:
                        prob_color = Fore.RED

                    print(f"[{ts}] Prob UP: {prob_color}{prob:.2%}{Style.RESET_ALL}")
                    
                    if prob > 0.65:
                         print(Fore.GREEN + Style.BRIGHT + ">>> STRONG BUY SIGNAL <<<")
                    elif prob < 0.35:
                         print(Fore.RED + Style.BRIGHT + ">>> STRONG SELL SIGNAL <<<")
                    
                else:
                    print(Fore.YELLOW + "No prediction data available yet.")
                    
            except Exception as e:
                print(Fore.RED + f"Prediction Error: {e}")
            
            # Sleep 5s
            time.sleep(5)
            
    except KeyboardInterrupt:
        print(Fore.MAGENTA + "\nStopping Live System...")
    finally:
        # cleanup
        print(Fore.MAGENTA + "Stopping Ingestion Service...")
        if 'ingestor' in locals():
            try:
                ingestor.stop()
            except Exception:
                pass
        print(Fore.MAGENTA + "Shutdown Complete.")

if __name__ == "__main__":
    main()
