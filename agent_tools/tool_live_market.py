from fastmcp import FastMCP
import os
from typing import Any, Dict, Optional

from integrations.polygon_data import PolygonData

mcp = FastMCP("LiveMarketData")

_data_client: Optional[PolygonData] = None


def _get_client() -> PolygonData:
    global _data_client
    if _data_client is None:
        _data_client = PolygonData()
    return _data_client


@mcp.tool()
def live_get_last_quote(symbol: str, asset_class: str = "equity") -> Dict[str, Any]:
    client = _get_client()
    if asset_class == "crypto":
        return client.get_last_crypto_quote(symbol)
    return client.get_last_quote(symbol)


@mcp.tool()
def live_get_bars(
    symbol: str,
    start: str,
    end: str,
    multiplier: int = 1,
    timespan: str = "minute",
    asset_class: str = "equity",
) -> Dict[str, Any]:
    client = _get_client()
    return client.get_aggregates(
        symbol=symbol,
        start=start,
        end=end,
        multiplier=multiplier,
        timespan=timespan,
        asset_class=asset_class,
    )


if __name__ == "__main__":
    port = int(os.getenv("LIVE_MARKET_HTTP_PORT", "8005"))
    mcp.run(transport="streamable-http", port=port)
