
import requests
import json
import time
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
        Finds the next resolving BTC Up/Down 5m market.
        Returns a dict with market details or None.
        """
        # We need to find active markets.
        # Searching for "Bitcoin 5m" or similar.
        # The slugs usually follow a pattern but IDs are safer if we can list them.
        # Let's try to query events with a keyword.
        
        params = {
            "limit": 50,
            "active": "true",
            "closed": "false",
            "order": "endDate",
            "ascending": "true",
            "tag_id": "1", # Crypto? or just search
        }
        
        # Searching is a bit tricky via undocumented API.
        # Let's try the /events endpoint with a broad query if possible, or filtered.
        # Best bet: Query markets sorted by endDate (soonest first)
        
        url = f"{self.GAMMA_API}/markets"
        # We want markets that are active, not closed.
        # We can client-side filter for "Bitcoin" and "5m".
        
        try:
            # Fetch a batch of upcoming expiring markets
            # "tag_id": "1" is often Crypto. Let's try searching by keyword if supported or just listing.
            # Gamma's GET /markets params are a bit guessy.
            # Let's try fetching active markets with limit
            
            # Fetch a batch of markets
            # "btc-up-or-down-5m" is the series slug we found.
            
            params = {
                "active": "true",
                "closed": "false",
                "order": "endDate",
                "ascending": "true",
                "limit": 100,
                "q": "Bitcoin" # Broader search, then filter by series
            }
            res = self.session.get(url, params=params, timeout=10)
            res.raise_for_status()
            markets = res.json()
            
            print(f"Fetched {len(markets)} markets.")
            
            for m in markets:
                # Filter by seriesSlug
                # Found seriesSlug: "btc-up-or-down-5m"
                series = m.get('seriesSlug', '')
                
                # Check for "btc-up-or-down-5m"
                if series == 'btc-up-or-down-5m':
                     return m
                
                # Fallback: check slug for similar pattern if series is missing
                slug = m.get('slug', '')
                if 'btc-updown-5m' in slug.lower():
                    return m
                     
            return None
            return None
            
        except Exception as e:
            print(f"Error fetching markets: {e}")
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

