
import sys
import os
import pandas as pd
import numpy as np
from typing import Dict, List

# Add parent directory to path to access src.database
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.database import DatabaseManager
from features import IndicatorLoader

class DatasetBuilder:
    def __init__(self, db_path: str = "../ohlcv.db"):
        # Adjust DB path logic if needed, assuming running from root usually
        self.db = DatabaseManager(db_path)
        self.loader = IndicatorLoader()
        self.loader.load_indicators()

    def build_mtf_dataset(self, source: str = "hyperliquid", limit: int = 50000) -> pd.DataFrame:
        """
        Builds a Multi-Timeframe dataset.
        1. Fetches 1m data (base).
        2. Fetches 3m, 5m, 15m data.
        3. Applies indicators to EACH independently.
        4. Merges higher TFs onto 1m base.
        """
        timeframes = ["1m", "3m", "5m", "15m"]
        dfs = {}
        
        # 1. Fetch & Feature Engineer each TF
        for tf in timeframes:
            print(f"Processing {tf} data...")
            # Fetch
            df = self.db.get_candles(source, "BTCUSDT", tf, limit=limit)
            
            if df.empty:
                # Fallback: Resample from 1m if available
                if tf != "1m" and "1m" in dfs:
                    print(f"Warning: No data for {tf} in DB. Resampling from 1m...")
                    df = self._resample_from_1m(dfs["1m"], tf)
                
                if df.empty:
                    print(f"Warning: No data for {tf}. Skipping.")
                    continue
            
            # Sort by time just in case
            df = df.sort_values('timestamp')
            
            # Apply Features
            # For 1m, no prefix needed (or maybe '1m_'? user didn't specify, usually base is clean)
            # Let's keep 1m clean, prefix others.
            prefix = f"{tf}_" if tf != "1m" else ""
            
            # If 1m, we might want to keep OHLC clean. 
            # If 3m, we want 3m_open, 3m_RSI, etc.
            # features.py renames NEW columns. 
            # We also want to rename the BASE columns (open, high, low...) for higher TFs.
            
            # First apply indicators (adds RSI, etc)
            df = self.loader.apply_all(df, prefix=prefix)
            
            # Normalize OHLCV (add n_open, n_close, etc)
            df = self.add_normalized_features(df, prefix=prefix)
            
            # Now rename the base OHLCV for higher TFs so they don't collide with 1m
            if tf != "1m":
                base_cols = ['open', 'high', 'low', 'close', 'volume']
                rename_map = {col: f"{prefix}{col}" for col in base_cols}
                df = df.rename(columns=rename_map)
            
            # Set index to timestamp for merging
            # If generated via resample, it might already be index?
            if 'timestamp' in df.columns:
                df = df.set_index('timestamp')
            
            dfs[tf] = df

        if "1m" not in dfs:
            raise ValueError("1m data is missing! Cannot build dataset.")
            
        # ... (Merge logic remains same)


        # 2. Merge - The 1m is the anchor
        base_df = dfs["1m"]
        
        # Merge others
        for tf, df_tf in dfs.items():
            if tf == "1m":
                continue
            
            # Resample calculation:
            # We want the 3m candle that covers the 1m time.
            # e.g. 1m candle at 12:01 belongs to 3m candle starting at 12:00.
            # 3m candle starts: 12:00, 12:03, 12:06.
            # 1m @ 12:00 -> 3m @ 12:00
            # 1m @ 12:01 -> 3m @ 12:00 (Forward fill? No, join on floor)
            
            # Strategy:
            # Create a join key in base_df for this timeframe.
            # 3m interval = 3 * 60 * 1000 ms = 180000 ms
            tf_min = int(tf[:-1])
            interval_ms = tf_min * 60 * 1000
            
            # Floor the 1m timestamp to nearest tf interval
            # Note: base_df.index is DatetimeIndex? 
            # DatabaseManager returns df['timestamp'] as datetime objects.
            # set_index makes it DatetimeIndex.
            
            # Vectorized floor:
            # Convert to int64 (ns), floor, convert back?
            # Or simpler:
            # We need to look up into df_tf which is indexed by its Start Time.
            
            # base_df index is the 1m start time.
            # The corresponding 3m candle also STARTS at floor(time, 3m).
            
            join_key = base_df.index.floor(f"{tf_min}min")
            
            # However, `floor` might behave oddly with timezones? 
            # Our data is UTC naive usually.
            
            # Let's map!
            # We enforce the join.
            
            # We can use pd.merge_asof with direction='backward' matching on time?
            # merge_asof backward: for 12:01, finds 12:00. Exact match finds exact.
            # This is perfect for "Looking at the most recent CLOSED or OPEN candle"?
            # Wait. 
            # If we are strictly historical:
            # At 12:01, the 3m candle (12:00-12:03) is NOT closed yet.
            # Do we want the "current developing" 3m candle? Or the "last closed" (11:57)?
            
            # USER SAID: "provide context of when the 3min looks like this"
            # In live trading, at 12:01, we only know the 3m candle SO FAR (partial).
            # But indicators on partial bars can be noisy/repainting.
            # However, our Aggregator writes "current state". 
            # So if we fetch history, we get the FINAL state of 12:00 at 12:01? 
            # No, history stores finalized candles.
            
            # If we simply join 12:01 to 12:00, we are using the FINALIZED 12:00 candle (which includes future info from 12:02!).
            # **DATA LEAKAGE WARNING**
            # If 1m is 12:01, and we join to 3m 12:00 (which closed at 12:03), 
            # we are telling the model about the future (12:02 price).
            
            # We should probably join to the PREVIOUS closed 3m candle? (11:57).
            # OR we accept we represent the "completed" set.
            # Usually for training, we want to predict 1m ahead.
            # If we use finalized higher TF, we leak.
            
            # SAFEST approach for simple training:
            # Join to the LAST CLOSED candle.
            # timestamp - interval?
            # Or `merge_asof` with tolerance or `allow_exact_matches=False`? 
            
            # Let's assume we want LAST COMPLETED context.
            # If 1m is 12:01.
            # Previous 3m closed at 12:00 (Start 11:57).
            # So 12:01 should see 11:57 data? Or 12:00 data?
            # 12:00 candle closes at 12:03.
            # So at 12:01, 12:00 is NOT ready.
            # So we must use 11:57 candle.
            # Join Key = floor(time - 1ms, 3m) - 3m?
            
            # Actually, let's keep it simple first. 
            # If we use Aggregator logic, we have "current state".
            # But DB history is only "closed" candles.
            # So we only have closed candles.
            # So at 12:01, the newest 3m candle in DB is 11:57.
            # So we matches 12:01 -> 11:57.
            
            # Implementation:
            # merge_asof(base, tf, on='timestamp', direction='backward')
            # But 12:01 backward finds 12:00? (If 12:00 exists).
            # If 12:00 exists in DB, it means it CLOSED at 12:03.
            # Ideally 12:01 shouldn't see 12:00.
            
            # To strictly avoid lookahead:
            # We must shift the higher TF data forward? 
            # Or ensure we only match to timestamps strictly LESS than current?
            # merge_asof direction='backward' includes exact matches.
            # If we exclude exact matches? 12:00 1m should not see 12:00 3m (which contains 12:00-12:03).
            # So 12:00 1m should see 11:57 3m.
            
            # Correct Logic:
            # Shift higher TF timestamps forward by their duration?
            # 11:57 candle (covers 11:57-12:00). Becomes available at 12:00.
            # So if we add +3m to its timestamp, it becomes 12:00.
            # Then at 12:00 1m, we match 12:00 3m.
            # Perfect.
            
            # 1. Shift TF df index by +TF duration.
            shifted_tf = df_tf.copy()
            shifted_tf.index = shifted_tf.index + pd.Timedelta(minutes=tf_min)
            
            # Ensure both are same dtype (ns)
            base_df.index = base_df.index.astype("datetime64[ns]")
            shifted_tf.index = shifted_tf.index.astype("datetime64[ns]")
            
            # 2. Merge asof backward
            # base_df is sorted.
            base_df = pd.merge_asof(
                base_df, 
                shifted_tf, 
                left_index=True, 
                right_index=True, 
                direction='backward'
            )

        # Drop rows where higher TFs are NaN (start of data)
        base_df = base_df.dropna()
        
        return base_df

    def add_normalized_features(self, df: pd.DataFrame, prefix: str = "") -> pd.DataFrame:
        """
        Adds normalized features:
        - n_open, n_high, n_low, n_close: Price / PrevClose - 1
        - n_volume: log1p(Volume)
        """
        df = df.copy()
        
        # Reference (Previous Close)
        prev_close = df['close'].shift(1)
        
        # Avoid division by zero/nan at start
        # fillna with open? or just drop first row later.
        
        df[f'{prefix}n_open'] = df['open'] / prev_close - 1
        df[f'{prefix}n_high'] = df['high'] / prev_close - 1
        df[f'{prefix}n_low'] = df['low'] / prev_close - 1
        df[f'{prefix}n_close'] = df['close'] / prev_close - 1
        df[f'{prefix}n_volume'] = np.log1p(df['volume'])
        
        # Normalize dynamic price-based indicators
        # They are already in df with their prefix (if any)
        for col in self.loader.latest_price_columns:
            if col in df.columns:
                # Naming convention: n_{col} 
                # e.g. 5m_EMA -> n_5m_EMA
                df[f'n_{col}'] = df[col] / prev_close - 1
        
        return df

    def _resample_from_1m(self, df_1m: pd.DataFrame, target_tf: str) -> pd.DataFrame:
        """
        Resamples 1m DataFrame (with int64 ms index) to target timeframe.
        Returns DataFrame with timestamp column and OHLCV.
        """
        # Select Only OHLCV
        df = df_1m[['open', 'high', 'low', 'close', 'volume']].copy()
        
        # Convert index to Datetime for resampling
        df.index = pd.to_datetime(df.index, unit='ms')
        
        # Parse minutes
        if target_tf.endswith('m'):
            minutes = int(target_tf[:-1])
            rule = f"{minutes}min"
        elif target_tf.endswith('h'):
            minutes = int(target_tf[:-1]) * 60
            rule = f"{minutes}min"
        else:
            rule = target_tf
            
        # Resample (Crypto standard: left label, left closed)
        resampled = df.resample(rule, closed='left', label='left').agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        })
        
        # Drop empty bins
        resampled = resampled.dropna()
        
        # Restore timestamp column (int64 ms)
        resampled['timestamp'] = resampled.index.astype(np.int64) // 10**6
        
        # Reset index to make 'timestamp' a column (as expected by logic that follows)
        # Actually logic says: if 'timestamp' in df.columns: set_index. 
        # So returning with timestamp column is safe.
        return resampled.reset_index(drop=True)

if __name__ == "__main__":
    builder = DatasetBuilder()
    df = builder.build_mtf_dataset(limit=1000)
    print(df.head())
    print(df.columns)
