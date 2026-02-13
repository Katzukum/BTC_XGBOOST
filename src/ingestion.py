
from binance.spot import Spot
from binance.websocket.spot.websocket_stream import SpotWebsocketStreamClient
from src.database import DatabaseManager
from src.aggregator import CandleAggregator
import time
import logging
import threading
import json
import pandas as pd

class BinanceIngestor:
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
        self.source = "binance"
        self.aggregator = CandleAggregator(db_manager, self.source)
        self.spot_client = Spot()
        self.ws_client = None
        self.running = False

    def fetch_history(self, symbol: str, interval: str, limit: int = 1000):
        print(f"Fetching history for {symbol} {interval}...")
        try:
            klines = self.spot_client.klines(symbol, interval, limit=limit)
            for k in klines:
                candle = {
                    't': k[0],
                    'o': k[1],
                    'h': k[2],
                    'l': k[3],
                    'c': k[4],
                    'v': k[5]
                }
                self.db.insert_candle(self.source, symbol, interval, candle)
            print(f"Fetched {len(klines)} historical candles.")
        except Exception as e:
            print(f"Error fetching history: {e}")

    def _on_message(self, _, message):
         try:
             if isinstance(message, str):
                 msg = json.loads(message)
             else:
                 msg = message
                 
             if 'k' in msg:
                 kline = msg['k']
                 symbol = msg.get('s')
                 interval = kline.get('i')
                 
                 if symbol and interval == '1m':
                      # Check if candle is closed
                      is_closed = kline.get('x', False)
                      
                      # 1. Store only if Closed
                      if is_closed:
                          self.db.insert_candle(self.source, symbol, interval, kline)
                      
                      # 2. Aggregate constantly (for live view)
                      tf_states = self.aggregator.process_1m_candle(kline)
                      
                      # Terminal Printing
                      timestamp = pd.to_datetime(kline.get('t'), unit='ms')
                      status = "[CLOSED]" if is_closed else "[OPEN]"
                      print(f"\n--- Binance Update {timestamp} {status} ---")
                      for tf, candle in tf_states.items():
                          o = candle['open']
                          h = candle['high']
                          l = candle['low']
                          c = candle['close']
                          #print(f"[{tf}] O: {o} H: {h} L: {l} C: {c}")

             elif 'e' in msg and msg['e'] == 'error':
                 print(f"WebSocket Error: {msg}")
         except Exception as e:
             print(f"Error parse message: {e}")

    def start_stream(self, symbol: str, interval: str):
        self.running = True
        if self.ws_client is None:
            self.ws_client = SpotWebsocketStreamClient(on_message=self._on_message)
        
        # Subscribe
        self.ws_client.kline(symbol=symbol, interval=interval)
        print(f"Subscribed to WebSocket stream for {symbol} {interval}")

    def stop(self):
        self.running = False
        if self.ws_client:
            self.ws_client.stop()
