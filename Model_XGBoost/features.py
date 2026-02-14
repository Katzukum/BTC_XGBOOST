
import os
import importlib.util
import pandas as pd
import glob
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("IndicatorLoader")

class IndicatorLoader:
    def __init__(self, indicators_dir: str = "indicators"):
        # Resolve absolute path relative to this file
        base_path = os.path.dirname(os.path.abspath(__file__))
        self.indicators_dir = os.path.join(base_path, indicators_dir)
        self.modules = []
        self.latest_price_columns = []

    def load_indicators(self):
        """
        Dynamically loads all .py modules from the indicators directory.
        """
        logger.info(f"Scanning for indicators in: {self.indicators_dir}")
        
        search_path = os.path.join(self.indicators_dir, "*.py")
        files = glob.glob(search_path)
        
        self.modules = []
        
        for file_path in files:
            module_name = os.path.basename(file_path)[:-3]
            if module_name.startswith("__"):
                continue
                
            try:
                spec = importlib.util.spec_from_file_location(module_name, file_path)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    
                    if hasattr(module, "calculate"):
                        self.modules.append(module)
                        logger.info(f"Loaded indicator: {module_name}")
                    else:
                        logger.warning(f"Skipping {module_name}: Missing 'calculate(df)' function.")
            except Exception as e:
                logger.error(f"Failed to load {module_name}: {e}")

    def apply_all(self, df: pd.DataFrame, prefix: str = "") -> pd.DataFrame:
        """
        Applies all loaded indicators to the dataframe.
        Args:
            df (pd.DataFrame): Input data.
            prefix (str): Prefix to add to new feature columns (e.g. "3m_").
        """
        if not self.modules:
            self.load_indicators()
            
        logger.info(f"Applying {len(self.modules)} indicators with prefix='{prefix}'...")
        
        # Track original columns to identify new ones
        original_cols = set(df.columns)
        
        # Reset tracker for this call
        self.latest_price_columns = []
        
        for module in self.modules:
            try:
                # expecting module.calculate(df) -> df
                # Snapshot columns before
                cols_before = set(df.columns)
                df = module.calculate(df)
                cols_after = set(df.columns)
                new_module_cols = cols_after - cols_before
                
                # Check for price-based flag
                if getattr(module, 'is_price_based', False):
                    self.latest_price_columns.extend(list(new_module_cols))
                    
            except Exception as e:
                logger.error(f"Error applying indicator {module.__name__}: {e}")
        
        # Rename ONLY the new columns if prefix is provided
        if prefix:
            new_cols = set(df.columns) - original_cols
            rename_map = {col: f"{prefix}{col}" for col in new_cols}
            df = df.rename(columns=rename_map)
            
            # Also update our tracked price columns to include the prefix
            self.latest_price_columns = [f"{prefix}{col}" for col in self.latest_price_columns]
                
        return df

    def add_fixed_target_features(self, df: pd.DataFrame, timeframe_mins: int = 5) -> pd.DataFrame:
        """
        Adds features specific to Fixed Target training (Polymarket style).
        - minutes_to_expiry: How many minutes left in the current block.
        - dist_to_block_open: (Current Close - Block Open) / Block Open
        
        Assumes df index is DatetimeIndex.
        """
        df = df.copy()
        
        # 1. Minutes to Expiry
        # Logic: 5m block starts at :00, ends at :05.
        # At :00, minutes_to_expiry = 5 (or 4? Let's say we are PREDICTING for :05)
        # Polymarket: Contract settles at :05.
        # Candle at :00 (covers :00-:01). Expiry is 5 mins away?
        # Let's count DOWN.
        # :00 -> 5
        # :01 -> 4
        # :02 -> 3
        # :03 -> 2
        # :04 -> 1
        # :05 -> 0 (Expiry happens/Settlement)
        
        # Calculation: 5 - (minute % 5)
        # Example: 12:00 -> 5 - 0 = 5
        # Example: 12:04 -> 5 - 4 = 1
        
        minutes = df.index.minute
        df['minutes_to_expiry'] = timeframe_mins - (minutes % timeframe_mins)
        
        # 2. Distance to Block Open
        # We need the 'open' of the 5m block.
        # Resample logic: Floor to 5m.
        
        # Group by 5m floor logic
        # We can use transform to broadcast the block open to every minute
        freq = f"{timeframe_mins}min"
        
        # Define a Grouper
        # Note: 'origin'='start' or 'epoch' usually aligns correctly
        grouper = pd.Grouper(freq=freq, origin='epoch')
        
        # Get Block Open
        block_open = df.groupby(grouper)['open'].transform('first')
        
        # Calculate Distance (Percentage)
        # (Close - BlockOpen) / BlockOpen
        df['dist_to_block_open'] = (df['close'] - block_open) / block_open
        
        return df

if __name__ == "__main__":
    # Test stub
    times = pd.date_range("2023-01-01 12:00", periods=10, freq="1min")
    df_dummy = pd.DataFrame({
        'open': [100, 101, 102, 103, 104, 105, 106, 107, 108, 109], 
        'close': [101, 102, 103, 104, 105, 106, 107, 108, 109, 110],
        'volume': [100]*10
    }, index=times)
    
    loader = IndicatorLoader()
    df_out = loader.add_fixed_target_features(df_dummy)
    print(df_out[['open', 'minutes_to_expiry', 'dist_to_block_open']].head(10))
