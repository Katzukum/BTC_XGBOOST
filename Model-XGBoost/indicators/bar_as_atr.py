import pandas as pd
import numpy as np

def calculate(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculates the BarAsATR indicator.
    
    Args:
        df (pd.DataFrame): Input dataframe with OHLCV data.
        
    Returns:
        pd.DataFrame: DataFrame with added columns:
            - BarATR_TopWick
            - BarATR_Body
            - BarATR_BottomWick
    """
    # Parameter settings
    atr_period = 14
    
    # Calculate True Range (TR)
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift()).abs()
    low_close = (df['low'] - df['close'].shift()).abs()
    
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    
    # Calculate ATR (Wilder's Smoothing)
    # Note: NinjaTrader's ATR is typically Wilder's Smoothing (alpha=1/per)
    # Pandas ewm(alpha=1/period, adjust=False) matches Wilder's
    atr = tr.ewm(alpha=1/atr_period, adjust=False).mean()
    
    # Avoid division by zero
    atr = atr.replace(0, np.nan)
    
    # Calculate components
    # Top Wick: High - Max(Open, Close)
    # Body: Close - Open
    # Bottom Wick: Min(Open, Close) - Low
    
    max_open_close = pd.concat([df['open'], df['close']], axis=1).max(axis=1)
    min_open_close = pd.concat([df['open'], df['close']], axis=1).min(axis=1)
    
    top_wick = df['high'] - max_open_close
    body = df['close'] - df['open']
    bottom_wick = min_open_close - df['low']
    
    # Normalize by ATR
    df['BarATR_TopWick'] = top_wick / atr
    df['BarATR_Body'] = body / atr
    df['BarATR_BottomWick'] = bottom_wick / atr
    
    return df
