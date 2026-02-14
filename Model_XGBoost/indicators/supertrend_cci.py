import pandas as pd
import numpy as np

def calculate(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculates the SuperTrendCCIv4 indicator.
    
    Args:
        df (pd.DataFrame): Input dataframe with OHLCV data.
        
    Returns:
        pd.DataFrame: DataFrame with added columns:
            - STCCI_CCI
            - STCCI_CCI_MA
            - STCCI_SuperTrend
            - STCCI_Trend (1 for Bullish, -1 for Bearish)
    """
    # 1. Parameter Settings (Updated per user request)
    cci_length = 48
    cci_smoothing = 18
    use_dema_smoothing = True
    
    st_factor = 3.0
    volatility_length = 21
    
    use_adaptive_factor = True
    er_length = 10
    st_factor_fast = 1.618
    st_factor_slow = 4.0
    
    # 2. Helper Functions
    def calculate_cci(high, low, close, length):
        tp = (high + low + close) / 3
        sma_tp = tp.rolling(window=length).mean()
        mean_dev = tp.rolling(window=length).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
        # Avoid division by zero
        mean_dev = mean_dev.replace(0, np.nan) 
        cci = (tp - sma_tp) / (0.015 * mean_dev)
        return cci

    def calculate_ema(series, span):
        return series.ewm(span=span, adjust=False).mean()

    def calculate_dema(series, span):
        ema1 = calculate_ema(series, span)
        ema2 = calculate_ema(ema1, span)
        return 2 * ema1 - ema2

    def calculate_sma(series, window):
        return series.rolling(window=window).mean()

    # 3. Calculate Base CCI
    raw_cci = calculate_cci(df['high'], df['low'], df['close'], cci_length)
    
    # 4. Apply Smoothing to CCI
    if cci_smoothing > 0:
        if use_dema_smoothing:
            cci_series = calculate_dema(raw_cci, cci_smoothing)
        else:
            cci_series = calculate_ema(raw_cci, cci_smoothing)
    else:
        cci_series = raw_cci
        
    # 5. Calculate Filtered MA (Visual Aid)
    # The C# code uses the same period as smoothing for the MA line
    ma_period = cci_smoothing if cci_smoothing > 0 else 9
    if use_dema_smoothing:
        cci_ma_series = calculate_dema(cci_series, ma_period)
    else:
        cci_ma_series = calculate_ema(cci_series, ma_period)

    # 6. Calculate Normalized Volatility
    # True Range of CCI itself
    cci_tr = (cci_series - cci_series.shift(1)).abs()
    
    if use_dema_smoothing:
        volatility_measure = calculate_dema(cci_tr, volatility_length)
    else:
        volatility_measure = calculate_sma(cci_tr, volatility_length)
        
    # Floor to 1 as per C# code
    volatility_measure = volatility_measure.clip(lower=1.0)
    
    # 7. Calculate Efficiency Ratio and Adaptive Factor
    adaptive_factor = pd.Series(st_factor, index=df.index)
    
    if use_adaptive_factor:
        # KAMA-style Efficiency Ratio on CCI
        change = (cci_series - cci_series.shift(er_length)).abs()
        
        # Volatility sum over ER length
        # Rolling sum of absolute differences
        diff_abs = (cci_series - cci_series.shift(1)).abs()
        volatility_sum = diff_abs.rolling(window=er_length).sum()
        
        er = change / volatility_sum
        er = er.fillna(0).clip(0, 1) # Handle div by zero and clamp
        
        # Adaptive Factor Logic from C#:
        # adaptiveFactor[0] = STFactorSlow - (er * (STFactorSlow - STFactorFast));
        adaptive_factor = st_factor_slow - (er * (st_factor_slow - st_factor_fast))
        
    # 8. Calculate SuperTrend Bands
    # Note: SuperTrend is recursive, so we need to iterate or use Numba/Cython for speed.
    # For now, we'll use a Python loop as it's cleaner to implement and likely fast enough for this usage.
    # Vectorizing SuperTrend with adaptive bands is tricky.
    
    upper_band = pd.Series(index=df.index, dtype='float64')
    lower_band = pd.Series(index=df.index, dtype='float64')
    supertrend = pd.Series(index=df.index, dtype='float64')
    trend_direction = pd.Series(index=df.index, dtype='float64') # 1 or -1
    
    # Pre-calculate basic bands
    basic_upper = cci_series + (adaptive_factor * volatility_measure)
    basic_lower = cci_series - (adaptive_factor * volatility_measure)
    
    # Initialize loop variables
    curr_upper = basic_upper.iloc[0]
    curr_lower = basic_lower.iloc[0]
    curr_trend = 1
    
    # Convert series to numpy arrays for faster iteration
    # Indices: 0=CCI, 1=BasicUpper, 2=BasicLower
    data_arr = np.column_stack([
        cci_series.values, 
        basic_upper.values, 
        basic_lower.values
    ])
    
    n = len(df)
    
    # Arrays to store results
    res_upper = np.full(n, np.nan)
    res_lower = np.full(n, np.nan)
    res_supertrend = np.full(n, np.nan)
    res_trend = np.full(n, 0) # 0 for init
    
    # We need to handle the warmup period where values might be NaN
    # Find first valid index where we have CCI and Volatility
    start_idx = 0
    for i in range(n):
        if not np.isnan(data_arr[i, 0]) and not np.isnan(data_arr[i, 1]):
            start_idx = i
            # Initialize with first valid values
            res_upper[i] = data_arr[i, 1]
            res_lower[i] = data_arr[i, 2]
            res_supertrend[i] = res_lower[i]
            res_trend[i] = 1
            break
            
    # Iterate from start_idx + 1
    for i in range(start_idx + 1, n):
        prev_upper = res_upper[i-1]
        prev_lower = res_lower[i-1]
        prev_trend = res_trend[i-1]
        
        curr_cci = data_arr[i, 0]
        curr_basic_upper = data_arr[i, 1]
        curr_basic_lower = data_arr[i, 2]
        prev_cci = data_arr[i-1, 0]
        
        # Upper band logic: Only moves down, never up (unless trend flips)
        if (curr_basic_upper < prev_upper) or (prev_cci > prev_upper):
            curr_upper = curr_basic_upper
        else:
            curr_upper = prev_upper
            
        # Lower band logic: Only moves up, never down (unless trend flips)
        if (curr_basic_lower > prev_lower) or (prev_cci < prev_lower):
            curr_lower = curr_basic_lower
        else:
            curr_lower = prev_lower
            
        res_upper[i] = curr_upper
        res_lower[i] = curr_lower
        
        # Trend Direction Logic
        if prev_trend == 1:
            if curr_cci <= curr_lower:
                curr_trend = -1
                res_supertrend[i] = curr_upper
            else:
                curr_trend = 1
                res_supertrend[i] = curr_lower
        else:
            if curr_cci >= curr_upper:
                curr_trend = 1
                res_supertrend[i] = curr_lower
            else:
                curr_trend = -1
                res_supertrend[i] = curr_upper
                
        res_trend[i] = curr_trend
        
    # Assign back to DataFrame columns
    df['STCCI_CCI'] = cci_series
    df['STCCI_CCI_MA'] = cci_ma_series
    df['STCCI_SuperTrend'] = pd.Series(res_supertrend, index=df.index)
    df['STCCI_Trend'] = pd.Series(res_trend, index=df.index)

    return df
