# Indicator Plugin Guide

This system uses a dynamic plugin architecture to load feature engineering logic. Each indicator should be a standalone Python file in the `indicators/` directory.

## File Structure

Create a new file in `Model-XGBoost/indicators/`, e.g., `my_indicator.py`.

## Required Format

Each plugin file **MUST** define a `calculate(df)` function.

### Signature
```python
def calculate(df: pd.DataFrame) -> pd.DataFrame:
    """
    Args:
        df (pd.DataFrame): The input dataframe containing OHLCV data.
                           Columns: 'open', 'high', 'low', 'close', 'volume'.
                           Index: DatetimeIndex or RangeIndex.
    
    Returns:
        pd.DataFrame: The dataframe with new feature columns added.
    """
```

### Example: RSI Indicator (`rsi.py`)

```python
import pandas as pd
import numpy as np

def calculate(df: pd.DataFrame) -> pd.DataFrame:
    # 1. Parameter settings
    period = 14
    
    # 2. Calculation logic
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    
    rs = gain / loss
    
    # 3. Add column to DF
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # 4. Return modified DF
    return df
```

## Automatic Normalization

To have your indicator automatically normalized like price data (e.g., for moving averages, VWAP, Bands), add the `is_price_based` flag to your module.

```python
is_price_based = True  # <--- Add this flag

def calculate(df: pd.DataFrame) -> pd.DataFrame:
    # ... logic ...
    df['EMA_20'] = df['close'].ewm(span=20).mean()
    return df
```
**Effect**: 
- The system will detect this flag.
- It will automatically create a normalized version of your columns: `n_{column_name}`.
- Formula: `(Value / Previous_Close) - 1`.


## Best Practices

1.  **Column Naming**: Use clear, descriptive column names (e.g., `RSI_14`, `SMA_50`).
2.  **No Side Effects**: Do not modify global state. Only modify and return the `df`.
3.  **Vectorization**: Use `pandas` or `numpy` vectorization. Avoid `for` loops for performance.
4.  **Error Handling**: If an indicator fails, the loader handles it, but try to ensure robust math (handle divide by zero).
