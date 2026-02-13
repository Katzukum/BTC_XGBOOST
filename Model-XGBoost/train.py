
import sys
import os
import pandas as pd
import numpy as np
import xgboost as xgb
import joblib
from sklearn.metrics import accuracy_score, classification_report
from dataset import DatasetBuilder

from features import IndicatorLoader

def prepare_data(df: pd.DataFrame, lookahead: int = 5) -> tuple:
    """
    Prepares features (X) and target (y) for Polymarket BTC Up/Down 5m.
    Target: 1 if Block Close > Block Open.
    Training on EVERY minute within the block.
    """
    df = df.copy()
    
    # 1. Add Fixed Target Features (Minutes to Expiry, Dist to Block Open)
    loader = IndicatorLoader()
    df = loader.add_fixed_target_features(df, timeframe_mins=lookahead)
    
    # 2. Define Target (Fixed 5m Block)
    # Polymarket: "Will BTC be above Open at 5m expiry?"
    # We define the block by 5m intervals.
    # Group by 5m, get 'open' of the first minute and 'close' of the last minute.
    
    freq = f"{lookahead}min"
    grouper = pd.Grouper(freq=freq, origin='epoch')
    
    # Broadcast Block Open and Block Close to all rows in the block
    block_open = df.groupby(grouper)['open'].transform('first')
    block_close = df.groupby(grouper)['close'].transform('last')
    
    # Target: Did the block close higher than it opened?
    df['target'] = (block_close > block_open).astype(int)
    
    # 3. Clean up edge cases
    # We might have the LAST block incomplete in the dataset.
    # If the last block is incomplete, 'block_close' might be the close of the CURRENT minute, 
    # which is data leakage if we treat it as the final settlement.
    # Actually, we should only look at completed blocks.
    # How to detect?
    # Count rows per group?
    # Or simply: validation logic.
    # If we are strictly historical, we assume the dataset creates 'block_close' from actual future data.
    # But for the very last rows, 'block_close' == 'current_close' (if it's the last row).
    # We must DROP the last incomplete block to avoid training on partial data.
    
    # Simple check: If minutes_to_expiry != 0 (or 1), we might be missing the end.
    # Robust way: Just drop the last 5 minutes of data to be safe.
    df = df.iloc[:-lookahead] 
    
    # 4. Define Features
    # Retain columns containing `n_`, `RSI`, and our new features.
    # explicitly keep 'minutes_to_expiry', 'dist_to_block_open'
    
    keep_keywords = ['n_', 'RSI', 'minutes_to_expiry', 'dist_to_block_open']
    feature_cols = [c for c in df.columns if any(k in c for k in keep_keywords)]
    
    # Drop rows where any feature is NaN (e.g. initial RSI warm up)
    df_clean = df.dropna(subset=feature_cols)
    
    X = df_clean[feature_cols]
    y = df_clean['target']
    
    return X, y

def main():
    # 1. Setup
    model_dir = os.path.join(os.path.dirname(__file__), 'models')
    os.makedirs(model_dir, exist_ok=True)
    
    # Calculate absolute path to ohlcv.db (in project root)
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    db_path = os.path.join(project_root, 'ohlcv.db')
    
    print(f"--- 1. Building Dataset (DB: {db_path}) ---")
    
    # [NEW] Refresh Data before training
    print(">>> Refreshing Data (Deep Clean 10k candles)...")
    # Hack to import from parent directory
    sys.path.append(project_root)
    from main import start_ingestion_service
    
    # CONFIG: Choose Source
    DATA_SOURCE = "BINANCE" # Options: "BINANCE", "HYPERLIQUID"

    # Start ingestion, drop old tables, fetch 10k candles
    # Pass the source explicitly
    ingestor = start_ingestion_service(source=DATA_SOURCE, drop_tables=True, limit=10000)
    
    # Stop the stream/threads, we only wanted the history
    print(">>> Data Refresh Complete. Stopping Ingestor...")
    ingestor.stop()
    
    builder = DatasetBuilder(db_path=db_path)
    # Fetch ample data
    df = builder.build_mtf_dataset(source=DATA_SOURCE.lower(), limit=50000)
    
    if df.empty:
        print("Dataset empty.")
        return

    print(f"Dataset Shape: {df.shape}")
    #save sample of the dataset
    df.head(10).to_csv("dataset_sample.csv", index=False)

    # 2. Prepare X, y
    print("\n--- 2. Preparing Target (Up/Down 5m) ---")
    X, y = prepare_data(df, lookahead=5)
    
    print(f"Features: {X.shape[1]}")
    print(f"Target Distribution:\n{y.value_counts(normalize=True)}")

    # 3. Split Train/Test (Time Series Split - No Shuffle)
    # 80% Train, 20% Test
    split_idx = int(len(X) * 0.8)
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]
    
    print(f"\n--- 3. Training XGBoost ({len(X_train)} samples) ---")
    
    model = xgb.XGBClassifier(
        n_estimators=100,
        learning_rate=0.1,
        max_depth=5,
        subsample=0.8,
        colsample_bytree=0.8,
        eval_metric='logloss',
        use_label_encoder=False
    )
    
    model.fit(
        X_train, y_train,
        eval_set=[(X_train, y_train), (X_test, y_test)],
        verbose=10
    )

    # 4. Evaluation
    print("\n--- 4. Evaluation ---")
    y_pred = model.predict(X_test)
    acc = accuracy_score(y_test, y_pred)
    
    print(f"Test Accuracy: {acc:.4f}")
    print("\nClassification Report:")
    print(classification_report(y_test, y_pred))

    # 5. Save
    model_path = os.path.join(model_dir, 'xgb_polymarket_5m.joblib')
    joblib.dump(model, model_path)
    print(f"\nModel saved to {model_path}")

if __name__ == "__main__":
    main()
