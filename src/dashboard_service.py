import os
import sys
import sqlite3
import random
from datetime import datetime, timezone, timedelta
from statistics import mean


class DashboardService:
    def __init__(self, project_root: str):
        self.project_root = project_root
        self.ohlcv_db = os.path.join(project_root, "ohlcv.db")
        self.trades_db = os.path.join(project_root, "trades.db")
        # Predictors are now managed externally by eel_app.py

    def _read_ohlcv(self, source: str = "BINANCE", limit: int = 250, timeframe: str = "1m"):
        if not os.path.exists(self.ohlcv_db):
            return []

        # Map timeframe to minutes
        tf_map = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240}
        minutes = tf_map.get(timeframe, 1)

        # Fetch more data if aggregating
        fetch_limit = limit * minutes
        
        # Determine table name
        # Source should be "binance" or "hyperliquid"
        table_source = source.lower()
        table_name = f"{table_source}_ohlcv_1m"

        conn = sqlite3.connect(self.ohlcv_db)
        cursor = conn.cursor()
        try:
            # Check if table exists first to avoid error
            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
            if not cursor.fetchone():
                return []

            cursor.execute(
                f"""
                SELECT timestamp, open, high, low, close, volume
                FROM {table_name}
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (fetch_limit,),
            )
            rows = cursor.fetchall()
        except sqlite3.OperationalError:
            rows = []
        finally:
            conn.close()

        # Data comes in DESC (newest first). Reverse to ASC for processing
        rows = list(reversed(rows))
        
        raw_candles = [
            {
                "timestamp": r[0],
                "open": r[1],
                "high": r[2],
                "low": r[3],
                "close": r[4],
                "volume": r[5],
            }
            for r in rows
        ]

        if timeframe == "1m":
             return raw_candles

        # Aggregation Logic
        aggregated = []
        current_candle = None
        
        # Helper to align timestamp to timeframe bucket
        def align_time(ts, mins):
            dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
            # Round down to nearest 'mins'
            minute = (dt.minute // mins) * mins
            truncated = dt.replace(minute=minute, second=0, microsecond=0)
            return int(truncated.timestamp() * 1000)

        for c in raw_candles:
            ts = c["timestamp"]
            bucket_ts = align_time(ts, minutes)

            if current_candle is None:
                current_candle = {
                    "timestamp": bucket_ts,
                    "open": c["open"],
                    "high": c["high"],
                    "low": c["low"],
                    "close": c["close"],
                    "volume": c["volume"]
                }
            elif bucket_ts == current_candle["timestamp"]:
                # Update current candle
                current_candle["high"] = max(current_candle["high"], c["high"])
                current_candle["low"] = min(current_candle["low"], c["low"])
                current_candle["close"] = c["close"]
                current_candle["volume"] += c["volume"]
            else:
                # New bucket, push old candle
                aggregated.append(current_candle)
                current_candle = {
                    "timestamp": bucket_ts,
                    "open": c["open"],
                    "high": c["high"],
                    "low": c["low"],
                    "close": c["close"],
                    "volume": c["volume"]
                }
        
        if current_candle:
            aggregated.append(current_candle)

        return aggregated[-limit:]

    def _read_trades(self, limit: int = 120):
        if not os.path.exists(self.trades_db):
            return []

        conn = sqlite3.connect(self.trades_db)
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT id, market_slug, prediction_side, prediction_prob,
                       entry_time, status, result_side, pnl, entry_price, profit_target
                FROM forward_trades
                ORDER BY entry_time DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()
        except sqlite3.OperationalError:
            rows = []
        finally:
            conn.close()

        trades = []
        for r in rows:
            pnl = r[7]
            trades.append(
                {
                    "id": r[0],
                    "slug": r[1],
                    "side": r[2] or "UP",
                    "probability": float(r[3]) if r[3] is not None else 0.5,
                    "entry_time": r[4],
                    "status": r[5] or "OPEN",
                    "result_side": r[6],
                    "pnl": float(pnl) if pnl is not None else None,
                    "entry_price": float(r[8]) if r[8] is not None else None,
                    "profit_target": float(r[9]) if r[9] is not None else None,
                }
            )
        return trades

    def _safe_iso(self, millis: int):
        return datetime.fromtimestamp(millis / 1000, tz=timezone.utc).isoformat()

    def get_snapshot(self, timeframe: str = "1m", source: str = "BINANCE", predictions: dict = None):
        """
        :param timeframe: Candle timeframe (e.g. 1m, 5m)
        :param source: "BINANCE" or "HYPERLIQUID" for chart data
        :param predictions: Dict of {source: {prob_up, time}}
        """
        candles = self._read_ohlcv(source=source, timeframe=timeframe)
        trades = self._read_trades()
        
        # Prepare Predictions List
        pm_odds = []
        if predictions:
            for src_name, pred_data in predictions.items():
                if pred_data:
                    pm_odds.append({
                        "source": src_name,
                        "prob_up": pred_data.get("prob_up", 0.5),
                        "time": pred_data.get("time", "")
                    })

        closes = [c["close"] for c in candles if c["close"] is not None]
        volumes = [c["volume"] for c in candles if c["volume"] is not None]

        last_price = closes[-1] if closes else 0.0
        start_price = closes[0] if len(closes) > 1 else last_price
        perf_pct = ((last_price - start_price) / start_price * 100.0) if start_price else 0.0

        closed = [t for t in trades if t["status"] == "CLOSED"]
        open_positions = [t for t in trades if t["status"] != "CLOSED"]
        pnls = [t["pnl"] for t in closed if t["pnl"] is not None]

        total_pnl = sum(pnls) if pnls else 0.0
        wins = len([p for p in pnls if p > 0])
        win_rate = (wins / len(pnls) * 100.0) if pnls else 0.0
        avg_trade = mean(pnls) if pnls else 0.0
        max_dd = min(pnls) if pnls else 0.0

        now = datetime.now(timezone.utc)
        next_window = now + timedelta(minutes=5 - (now.minute % 5), seconds=-now.second)

        order_feed = []
        # Populate order feed from trades if available, otherwise dummies
        for t in trades[:12]:
            size = (t["entry_price"] or 0.5) * 10000
            side = t["side"]
            order_feed.append(
                {
                    "time": (t["entry_time"] or "")[-14:-6],
                    "window": "5m",
                    "side": side,
                    "entry": round((t["entry_price"] or 0.5) * 100, 2),
                    "size": round(size, 2),
                }
            )

        exchanges = ["BIN", "CB", "OKX", "KRK", "BYB", "DER", "HL"]
        signal_flow = [
            {
                "exchange": ex,
                "signal": round(random.uniform(-1.0, 1.0), 2),
                "latency": random.randint(8, 75),
            }
            for ex in exchanges
        ]

        return {
            "header": {
                "asset": "BTC/USD",
                "price": round(last_price, 2),
                "total_pnl": round(total_pnl, 2),
                "daily_pnl": round(total_pnl * 0.126, 2),
                "win_rate": round(win_rate, 2),
                "total_trades": len(trades),
                "open_exposure": round(sum((t["entry_price"] or 0.5) * 1000 for t in open_positions), 2),
                "next_window_seconds": max(0, int((next_window - now).total_seconds())),
                "market_session": f"{now.strftime('%I:%M%p')}–{(now + timedelta(minutes=5)).strftime('%I:%M%p')} UTC",
            },
            "performance": {
                "total": round(total_pnl, 2),
                "return_pct": round(perf_pct, 2),
                "avg_trade": round(avg_trade, 2),
                "max_dd": round(max_dd, 2),
                "kelly_f": round(min(10.0, max(0.5, win_rate / 20)), 2),
                "sharpe": round((mean(pnls) / (abs(max_dd) + 1.0)) * 8, 2) if pnls else 0.0,
                "dd_limit": -5.0,
            },
            "charts": {
                "timestamps": [self._safe_iso(c["timestamp"]) for c in candles][-120:],
                "prices": closes[-120:],
                "equity": [round(sum(pnls[: i + 1]), 2) for i in range(len(pnls))][-120:],
                "volumes": volumes[-120:],
                "candles": candles, 
            },
            "order_feed": order_feed,
            "signal_flow": signal_flow,
            "positions_log": trades[:18],
            "execution_pipeline": {
                "cex_feeds": "Binance, Hyperliquid",
                "pm_odds": pm_odds, # Now a list
                "edge": f"edge {round(perf_pct / 6, 2)}%",
                "kelly": f"f* {round(min(8.0, max(1.0, win_rate / 20)), 2)}%",
                "exec": f"EV ${round(avg_trade, 2)}",
            },
        }
