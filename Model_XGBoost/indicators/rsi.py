
import pandas as pd
import numpy as np

def calculate(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculates RSI (Relative Strength Index) for a 14-period window.
    Adds 'RSI_14' column.
    """
    period = 14
    
    # Check if we have enough data
    if len(df) < period:
        df[f'RSI_{period}'] = np.nan
        return df
        
    close_delta = df['close'].diff()

    # Make two series: one for gains and one for losses
    up = close_delta.clip(lower=0)
    down = -1 * close_delta.clip(upper=0)
    
    # Calculate the EWMA
    ma_up = up.ewm(com=period - 1, adjust=True, min_periods=period).mean()
    ma_down = down.ewm(com=period - 1, adjust=True, min_periods=period).mean()

    rsi = ma_up / ma_down
    rsi = 100 - (100 / (1 + rsi))
    
    df[f'RSI_{period}'] = rsi
    
    return df
