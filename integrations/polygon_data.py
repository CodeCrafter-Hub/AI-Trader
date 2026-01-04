import os
from typing import Any, Dict, Optional

import requests


class PolygonData:
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, timeout: int = 10) -> None:
        self.api_key = api_key or os.getenv("POLYGON_API_KEY")
        self.base_url = base_url or os.getenv("POLYGON_BASE_URL", "https://api.polygon.io")
        self.timeout = timeout

    def _request(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self.api_key:
            raise ValueError("POLYGON_API_KEY must be set")
        url = f"{self.base_url}{path}"
        params = params or {}
        params["apiKey"] = self.api_key
        response = requests.get(url, params=params, timeout=self.timeout)
        if not response.ok:
            raise RuntimeError(f"Polygon API error {response.status_code}: {response.text}")
        return response.json()

    @staticmethod
    def _normalize_crypto_symbol(symbol: str) -> str:
        cleaned = symbol.replace("-", "/").upper()
        if "/" not in cleaned:
            return cleaned
        base, quote = cleaned.split("/", 1)
        return f"X:{base}{quote}"

    def get_last_quote(self, symbol: str) -> Dict[str, Any]:
        payload = self._request(f"/v2/last/nbbo/{symbol.upper()}")
        last = payload.get("results", {}) if isinstance(payload, dict) else {}
        return {
            "symbol": symbol.upper(),
            "bid": last.get("p"),
            "ask": last.get("P"),
            "bid_size": last.get("s"),
            "ask_size": last.get("S"),
            "timestamp": last.get("t"),
        }

    def get_last_crypto_quote(self, symbol: str) -> Dict[str, Any]:
        cleaned = symbol.replace("-", "/").upper()
        if "/" not in cleaned:
            raise ValueError("Crypto symbol must be like BTC/USD")
        base, quote = cleaned.split("/", 1)
        payload = self._request(f"/v2/last/crypto/{base}/{quote}")
        last = payload.get("last", {}) if isinstance(payload, dict) else {}
        return {
            "symbol": cleaned,
            "bid": last.get("bid"),
            "ask": last.get("ask"),
            "bid_size": last.get("bidSize"),
            "ask_size": last.get("askSize"),
            "timestamp": last.get("timestamp"),
        }

    def get_aggregates(
        self,
        symbol: str,
        start: str,
        end: str,
        multiplier: int = 1,
        timespan: str = "minute",
        asset_class: str = "equity",
    ) -> Dict[str, Any]:
        if asset_class == "crypto":
            ticker = self._normalize_crypto_symbol(symbol)
        else:
            ticker = symbol.upper()
        path = f"/v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{start}/{end}"
        return self._request(path)
