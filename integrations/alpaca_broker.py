import os
from typing import Any, Dict, Optional

import requests


class AlpacaBroker:
    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: int = 10,
    ) -> None:
        self.api_key = api_key or os.getenv("ALPACA_API_KEY")
        self.api_secret = api_secret or os.getenv("ALPACA_API_SECRET")
        self.base_url = base_url or os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        if not self.api_key or not self.api_secret:
            raise ValueError("ALPACA_API_KEY and ALPACA_API_SECRET must be set")
        return {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.api_secret,
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        response = requests.request(
            method,
            url,
            headers=self._headers(),
            params=params,
            json=json_body,
            timeout=self.timeout,
        )
        if not response.ok:
            raise RuntimeError(f"Alpaca API error {response.status_code}: {response.text}")
        try:
            return response.json()
        except ValueError:
            return {"raw": response.text}

    def get_account(self) -> Dict[str, Any]:
        return self._request("GET", "/v2/account")

    def list_positions(self) -> Dict[str, Any]:
        return self._request("GET", "/v2/positions")

    def get_clock(self) -> Dict[str, Any]:
        return self._request("GET", "/v2/clock")

    def submit_order(
        self,
        symbol: str,
        side: str,
        qty: Optional[float] = None,
        notional: Optional[float] = None,
        order_type: str = "market",
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
        time_in_force: Optional[str] = None,
        client_order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not qty and notional is None:
            raise ValueError("Either qty or notional must be provided")

        payload: Dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
        }
        if qty is not None:
            payload["qty"] = qty
        if notional is not None:
            payload["notional"] = notional
        if limit_price is not None:
            payload["limit_price"] = limit_price
        if stop_price is not None:
            payload["stop_price"] = stop_price
        if time_in_force:
            payload["time_in_force"] = time_in_force
        if client_order_id:
            payload["client_order_id"] = client_order_id

        return self._request("POST", "/v2/orders", json_body=payload)

    def cancel_all_orders(self) -> Dict[str, Any]:
        return self._request("DELETE", "/v2/orders")
