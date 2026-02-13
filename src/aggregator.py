
from typing import Dict, Any, List
import pandas as pd
from src.database import DatabaseManager

class CandleAggregator:
    def __init__(self, db_manager: DatabaseManager, source: str):
        self.db = db_manager
        self.source = source
        self.targets = [3, 5, 15] 
        # Buffer to hold the current building candle for each timeframe
        # Format: { 3: {'start': 1000, 'candle': {...}}, 5: ... }
        self.buffer = {}

    def process_1m_candle(self, candle: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """
        Takes a verified closed 1m candle and updates higher timeframe candles in memory.
        Flushes to DB only when a bucket closes.
        Returns a dictionary of the current state of all tracked timeframes.
        """
        # Parse inputs
        timestamp = int(candle.get('t') or candle.get('timestamp'))
        open_price = float(candle.get('o') or candle.get('open'))
        high = float(candle.get('h') or candle.get('high'))
        low = float(candle.get('l') or candle.get('low'))
        close = float(candle.get('c') or candle.get('close'))
        volume = float(candle.get('v') or candle.get('volume'))
        
        current_candle = {
            'timestamp': timestamp,
            'open': open_price,
            'high': high,
            'low': low,
            'close': close,
            'volume': volume
        }

        results = {"1m": current_candle}

        for tf in self.targets:
            agg_candle = self._update_timeframe_buffer(tf, current_candle)
            results[f"{tf}m"] = agg_candle
            
        return results

    def _update_timeframe_buffer(self, timeframe_minutes: int, candle_1m: Dict[str, Any]) -> Dict[str, Any]:
        # Calculate start of the bucket
        interval_ms = timeframe_minutes * 60 * 1000
        current_ts = candle_1m['timestamp']
        bucket_start = (current_ts // interval_ms) * interval_ms
        
        # Check buffer
        buffered = self.buffer.get(timeframe_minutes)
        
        if buffered:
            last_bucket_start = buffered['start']
            last_candle = buffered['candle']
            
            if bucket_start == last_bucket_start:
                # Same bucket, just update in memory
                new_candle = {
                    'timestamp': bucket_start,
                    'open': last_candle['open'],
                    'high': max(last_candle['high'], candle_1m['high']),
                    'low': min(last_candle['low'], candle_1m['low']),
                    'close': candle_1m['close'],
                    'volume': last_candle['volume'] + candle_1m['volume']
                }
                self.buffer[timeframe_minutes] = {'start': bucket_start, 'candle': new_candle}
                return new_candle
            else:
                # New bucket started! 
                # 1. Flush the COMPLETED candle (last_candle) to DB
                self.db.insert_candle(self.source, "BTCUSDT", f"{timeframe_minutes}m", last_candle)
                
                # 2. Start new bucket
                new_candle = self._create_new_bucket(bucket_start, candle_1m)
                self.buffer[timeframe_minutes] = {'start': bucket_start, 'candle': new_candle}
                return new_candle
        else:
            # First run, init buffer (try to load from DB just in case of restart?)
            # For simplest performance, we start fresh or assuming sync. 
            # If we want to be perfect, we'd check DB once at start.
            # Let's assume start fresh for now to kill latency.
            new_candle = self._create_new_bucket(bucket_start, candle_1m)
            self.buffer[timeframe_minutes] = {'start': bucket_start, 'candle': new_candle}
            return new_candle

    def _create_new_bucket(self, start_ts: int, candle: Dict[str, Any]) -> Dict[str, Any]:
        return {
            'timestamp': start_ts,
            'open': candle['open'],
            'high': candle['high'],
            'low': candle['low'],
            'close': candle['close'],
            'volume': candle['volume']
        }
