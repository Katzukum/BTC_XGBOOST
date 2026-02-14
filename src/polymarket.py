
import requests
import json
import time

from datetime import datetime, timezone

class PolymarketClient:
    GAMMA_API = "https://gamma-api.polymarket.com"
    clob_api = "https://clob.polymarket.com"

    def __init__(self):
        self.session = requests.Session()

    def get_market_by_slug(self, slug):
        """
        Fetches a market by its slug.
        """
        url = f"{self.GAMMA_API}/markets"
        params = {"slug": slug}
        try:
            res = self.session.get(url, params=params)
            res.raise_for_status()
            data = res.json()
            # Gamma /markets with slug param matches exactly or returns list? 
            # Usually returns a list of matches. We expect one.
            if isinstance(data, list):
                if data:
                    return data[0]
                else:
                    return None
            return data
        except Exception as e:
            print(f"Error fetching market by slug {slug}: {e}")
            return None

    def find_next_btc_5m_market(self):
        """
        Finds the next resolving BTC Up/Down 5m market using direct slug lookup.
        """
        # Calculate current and next 5m epochs
        now = datetime.now(timezone.utc)
        remainder = now.minute % 5
        current_epoch_time = now.replace(minute=now.minute - remainder, second=0, microsecond=0)
        current_epoch = int(current_epoch_time.timestamp())
        
        # We usually want the one closing in future. 
        # Markets are usually named by their CLOSE time or START time?
        # Sim trades use `btc-up-or-down-5m-{epoch}` where epoch is START time?
        # Let's check a few future intervals to be safe.
        
        epochs_to_check = [current_epoch, current_epoch + 300, current_epoch + 600]
        
        for epoch in epochs_to_check:
            # Slug format: btc-updown-5m-{epoch}
            slug = f"btc-updown-5m-{epoch}"
            # print(f"Checking slug: {slug}")
            
            market = self.get_market_by_slug(slug)
            if market and market.get('closed') is False:
                # print(f"Found active market: {slug}")
                return market
                
        return None

    def get_market(self, condition_id):
        url = f"{self.GAMMA_API}/markets/{condition_id}"
        try:
            res = self.session.get(url)
            if res.status_code == 404:
                return None
            res.raise_for_status()
            return res.json()
        except Exception as e:
            print(f"Error fetching market {condition_id}: {e}")
            return None
            
    def get_market_resolution(self, condition_id):
        """
        Checks if the market has resolved.
        Returns: 'UP', 'DOWN', or None (not resolved)
        """
        m = self.get_market(condition_id)
        if not m:
            return None
            
        # Check resolution
        if m.get('closed') is True:
            # 1. Try tokens array (legacy or some markets)
            tokens = m.get('tokens', [])
            for t in tokens:
                if t.get('winner') is True:
                     outcome = t.get('outcome') # "Yes" or "No"
                     return outcome
            
            # 2. Try outcomePrices and outcomes (JSON strings in new API)
            try:
                op_str = m.get('outcomePrices')
                oc_str = m.get('outcomes')
                
                if op_str and oc_str:
                    prices = json.loads(op_str)
                    outcomes = json.loads(oc_str)
                    
                    if len(prices) == len(outcomes):
                        # Find winner (price == 1)
                        for i, p in enumerate(prices):
                            # Convert to float just in case
                            if float(p) >= 0.99: # Allow small epsilon if needed, usually exactly "1"
                                return outcomes[i]
            except Exception as e:
                print(f"Error parsing resolution for {condition_id}: {e}")
            
        return None

    def get_token_price(self, token_id, side='buy'):
        """
        Fetches the live price for a token from the CLOB.
        """
        url = f"{self.clob_api}/price"
        params = {"token_id": token_id, "side": side}
        try:
            res = self.session.get(url, params=params, timeout=5)
            # res.status_code might be 404 if no orders
            if res.status_code == 200:
                data = res.json()
                return data.get('price')
            return None
        except Exception as e:
            print(f"Error fetching price for {token_id}: {e}")
            return None

    def enrich_market_with_prices(self, market):
        """
        Updates the 'outcomePrices' in the market dict with live CLOB prices.
        """
        try:
            # Parse outcomes and clobTokenIds
            outcomes_str = market.get('outcomes', '[]')
            clob_ids_str = market.get('clobTokenIds', '[]')
            
            if isinstance(outcomes_str, str):
                outcomes = json.loads(outcomes_str)
            else:
                outcomes = outcomes_str
                
            if isinstance(clob_ids_str, str):
                clob_ids = json.loads(clob_ids_str)
            else:
                clob_ids = clob_ids_str
                
            if not clob_ids or len(clob_ids) != len(outcomes):
                return market

            new_prices = []
            for i, _ in enumerate(outcomes):
                token_id = clob_ids[i]
                price = self.get_token_price(token_id, side="buy")
                # If no price, fallback to existing or 0
                if price is None:
                    # try to get from existing outcomePrices if available
                    op_str = market.get('outcomePrices')
                    if op_str:
                         try:
                             existing = json.loads(op_str) if isinstance(op_str, str) else op_str
                             price = existing[i]
                         except:
                             price = 0
                
                new_prices.append(str(price) if price is not None else "0")
            
            # Update the market dict
            # Frontend expects JSON string for outcomePrices usually, or we can just set it as list
            # The current frontend handles both string and list.
            market['outcomePrices'] = new_prices
            # market['outcomePrices'] = json.dumps(new_prices) # Keep as list for internal use is better
            
            return market
        except Exception as e:
            print(f"Error enriching market prices: {e}")
            return market
