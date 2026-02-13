import sys
import os
import joblib
import pandas as pd
import numpy as np
import time
from dataset import DatasetBuilder

class Predictor:
    def __init__(self, model_path=None, source="hyperliquid"):
        if model_path is None:
            model_path = os.path.join(os.path.dirname(__file__), 'models', 'xgb_polymarket_5m.joblib')
        
        self.source = source
        self.model_path = model_path
        self.model = None
        
        # Calculate absolute path to DB (Project Root / ohlcv.db)
        # predict.py is in Model-XGBoost/
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        db_path = os.path.join(project_root, 'ohlcv.db')
        
        self.builder = DatasetBuilder(db_path=db_path) 
        self.load_model()

    def load_model(self):
        if not os.path.exists(self.model_path):
            print(f"Error: Model not found at {self.model_path}")
            return
        print(f"Loading Model from {self.model_path}...")
        self.model = joblib.load(self.model_path)

    def predict_latest(self):
        if not self.model:
            print("Model not loaded.")
            return None

        # Fetch Data (Enough history for indicators)
        # We need enough valid history for RSI14 + Normalization (Shift 1)
        # 100 is plenty.
        df = self.builder.build_mtf_dataset(source=self.source, limit=200)
        
        if df.empty:
            print("Error: No data fetched.")
            return None

        # Add Fixed Target Features
        # calculating minutes_to_expiry and dist_to_block_open
        df = self.builder.loader.add_fixed_target_features(df, timeframe_mins=5)

        # Feature selection logic MUST match training
        keep_keywords = ['n_', 'RSI', 'minutes_to_expiry', 'dist_to_block_open']
        feature_cols = [c for c in df.columns if any(k in c for k in keep_keywords)]
        
        # Get last row (Current State)
        last_row = df.iloc[[-1]][feature_cols]
        current_time = df.index[-1]
        
        # Predict
        probs = self.model.predict_proba(last_row)[0]
        prob_up = probs[1]
        
        return {
            "time": current_time,
            "prob_up": prob_up,
            "features": last_row.to_dict(orient='records')[0]
        }

def main():
    predictor = Predictor()
    result = predictor.predict_latest()
    
    if result:
        prob_up = result['prob_up']
        print(f"\n--- Prediction for Candle {result['time']} ---")
        print(f"Probability UP (Close > Open in 5m): {prob_up:.2%}")
        
        if prob_up > 0.6:
            print(">> SIGNAL: BULLISH POSITION")
        elif prob_up < 0.4:
            print(">> SIGNAL: BEARISH POSITION")
        else:
            print(">> SIGNAL: NEUTRAL / NO TRADE")

if __name__ == "__main__":
    main()
