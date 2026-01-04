from fastmcp import FastMCP
import os
import time
from typing import Any, Dict, Optional, List

from integrations.alpaca_broker import AlpacaBroker
from tools.live_risk_state import get_or_init_day_state
from tools.live_alerts import notify_alert

mcp = FastMCP("LiveTradeTools")

_broker: Optional[AlpacaBroker] = None


def _get_broker() -> AlpacaBroker:
    global _broker
    if _broker is None:
        _broker = AlpacaBroker()
    return _broker


def _get_env_float(key: str) -> Optional[float]:
    value = os.getenv(key)
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _ensure_notional_limits(notional: float, equity: Optional[float]) -> Optional[str]:
    max_notional = _get_env_float("MAX_ORDER_NOTIONAL_USD")
    max_pct = _get_env_float("MAX_ORDER_PCT_EQUITY")

    if max_notional is not None and notional > max_notional:
        return f"Order notional {notional} exceeds MAX_ORDER_NOTIONAL_USD {max_notional}"
    if max_pct is not None and equity:
        if notional > equity * max_pct:
            return f"Order notional {notional} exceeds MAX_ORDER_PCT_EQUITY {max_pct}"
    return None


def _get_position_qty(positions: Any, symbol: str) -> float:
    if not isinstance(positions, list):
        return 0.0
    for pos in positions:
        if isinstance(pos, dict) and pos.get("symbol") == symbol:
            try:
                return float(pos.get("qty", 0))
            except ValueError:
                return 0.0
    return 0.0


def _get_position_notional(positions: Any, symbol: str) -> float:
    if not isinstance(positions, list):
        return 0.0
    for pos in positions:
        if isinstance(pos, dict) and pos.get("symbol") == symbol:
            try:
                return abs(float(pos.get("market_value", 0)))
            except ValueError:
                return 0.0
    return 0.0


def _estimate_order_notional(
    qty: Optional[float],
    notional: Optional[float],
    estimated_price: Optional[float],
) -> Optional[float]:
    if notional is not None:
        return notional
    if qty is None:
        return None
    if estimated_price is None:
        return None
    return float(qty) * float(estimated_price)


def _get_env_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _get_env_float_default(key: str, default: float) -> float:
    raw = os.getenv(key)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _daily_loss_exceeded(equity: Optional[float]) -> Optional[str]:
    if equity is None:
        return None
    max_loss_pct = _get_env_float("MAX_DAILY_LOSS_PCT")
    if max_loss_pct is None:
        return None
    day_state = get_or_init_day_state(equity)
    equity_start = day_state.get("equity_start")
    if not equity_start:
        return None
    drawdown = max(0.0, (equity_start - equity) / equity_start)
    if drawdown >= max_loss_pct:
        return f"Daily loss {drawdown:.2%} exceeds MAX_DAILY_LOSS_PCT {max_loss_pct:.2%}"
    return None


def _ensure_position_limits(
    current_notional: float,
    order_notional: float,
    equity: Optional[float],
) -> Optional[str]:
    max_pos_notional = _get_env_float("MAX_POSITION_NOTIONAL_USD")
    max_pos_pct = _get_env_float("MAX_POSITION_PCT_EQUITY")
    new_notional = current_notional + order_notional
    if max_pos_notional is not None and new_notional > max_pos_notional:
        return f"Position notional {new_notional} exceeds MAX_POSITION_NOTIONAL_USD {max_pos_notional}"
    if max_pos_pct is not None and equity:
        if new_notional > equity * max_pos_pct:
            return f"Position notional {new_notional} exceeds MAX_POSITION_PCT_EQUITY {max_pos_pct}"
    return None


def _split_equity_qty(total_qty: float, slices: int) -> List[float]:
    if slices <= 1:
        return [float(total_qty)]
    base = int(total_qty) // slices
    remainder = int(total_qty) % slices
    if base <= 0:
        return [float(int(total_qty))]
    quantities = [float(base)] * slices
    for idx in range(remainder):
        quantities[idx] += 1.0
    return [q for q in quantities if q > 0]


def _split_notional(total_notional: float, slices: int) -> List[float]:
    if slices <= 1:
        return [float(total_notional)]
    per_slice = float(total_notional) / float(slices)
    return [per_slice] * slices


@mcp.tool()
def live_get_account() -> Dict[str, Any]:
    broker = _get_broker()
    return broker.get_account()


@mcp.tool()
def live_get_positions() -> Dict[str, Any]:
    broker = _get_broker()
    return broker.list_positions()


@mcp.tool()
def live_get_clock() -> Dict[str, Any]:
    broker = _get_broker()
    return broker.get_clock()


@mcp.tool()
def live_cancel_all_orders() -> Dict[str, Any]:
    broker = _get_broker()
    return broker.cancel_all_orders()


@mcp.tool()
def live_buy(
    symbol: str,
    qty: Optional[float] = None,
    notional: Optional[float] = None,
    estimated_price: Optional[float] = None,
    order_type: str = "market",
    limit_price: Optional[float] = None,
    stop_price: Optional[float] = None,
    time_in_force: Optional[str] = None,
    asset_class: str = "equity",
) -> Dict[str, Any]:
    if qty is None and notional is None:
        return {"error": "Either qty or notional must be provided"}

    broker = _get_broker()
    account = broker.get_account()
    equity = None
    buying_power = None
    try:
        equity = float(account.get("equity"))
    except (TypeError, ValueError):
        equity = None
    try:
        buying_power = float(account.get("buying_power"))
    except (TypeError, ValueError):
        buying_power = None

    order_notional = _estimate_order_notional(qty, notional, estimated_price)
    if order_notional is None and any(
        _get_env_float(key) is not None
        for key in (
            "MAX_ORDER_NOTIONAL_USD",
            "MAX_ORDER_PCT_EQUITY",
            "MAX_POSITION_NOTIONAL_USD",
            "MAX_POSITION_PCT_EQUITY",
        )
    ):
        return {"error": "estimated_price is required when qty is used with notional limits"}

    loss_error = _daily_loss_exceeded(equity)
    if loss_error:
        notify_alert("risk_limit_triggered", {"type": "daily_loss", "symbol": symbol, "details": loss_error})
        return {"error": loss_error}

    if order_notional is not None:
        limit_error = _ensure_notional_limits(order_notional, equity)
        if limit_error:
            notify_alert("risk_limit_triggered", {"type": "order_notional", "symbol": symbol, "details": limit_error})
            return {"error": limit_error}
        if buying_power is not None and order_notional > buying_power:
            notify_alert("risk_limit_triggered", {"type": "buying_power", "symbol": symbol, "details": "Insufficient buying power"})
            return {"error": "Insufficient buying power", "buying_power": buying_power}

        positions = live_get_positions()
        current_notional = _get_position_notional(positions, symbol)
        position_error = _ensure_position_limits(current_notional, order_notional, equity)
        if position_error:
            notify_alert("risk_limit_triggered", {"type": "position_limit", "symbol": symbol, "details": position_error})
            return {"error": position_error}

    tif = time_in_force
    if tif is None:
        tif = "gtc" if asset_class == "crypto" else "day"

    try:
        return broker.submit_order(
            symbol=symbol,
            side="buy",
            qty=qty,
            notional=notional,
            order_type=order_type,
            limit_price=limit_price,
            stop_price=stop_price,
            time_in_force=tif,
        )
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def live_sell(
    symbol: str,
    qty: Optional[float] = None,
    notional: Optional[float] = None,
    estimated_price: Optional[float] = None,
    order_type: str = "market",
    limit_price: Optional[float] = None,
    stop_price: Optional[float] = None,
    time_in_force: Optional[str] = None,
    asset_class: str = "equity",
) -> Dict[str, Any]:
    if qty is None and notional is None:
        return {"error": "Either qty or notional must be provided"}

    allow_short = os.getenv("ALLOW_SHORT", "false").lower() == "true"
    if not allow_short and qty is not None:
        positions = live_get_positions()
        current_qty = _get_position_qty(positions, symbol)
        if qty > current_qty:
            return {"error": "Shorting disabled or insufficient position", "current_qty": current_qty}

    tif = time_in_force
    if tif is None:
        tif = "gtc" if asset_class == "crypto" else "day"

    broker = _get_broker()
    try:
        return broker.submit_order(
            symbol=symbol,
            side="sell",
            qty=qty,
            notional=notional,
            order_type=order_type,
            limit_price=limit_price,
            stop_price=stop_price,
            time_in_force=tif,
        )
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def live_place_order(
    symbol: str,
    side: str,
    qty: Optional[float] = None,
    notional: Optional[float] = None,
    estimated_price: Optional[float] = None,
    order_type: str = "market",
    limit_price: Optional[float] = None,
    stop_price: Optional[float] = None,
    time_in_force: Optional[str] = None,
    asset_class: str = "equity",
) -> Dict[str, Any]:
    side = side.lower()
    if side not in ("buy", "sell"):
        return {"error": "side must be buy or sell"}
    if side == "buy":
        return live_buy(
            symbol=symbol,
            qty=qty,
            notional=notional,
            estimated_price=estimated_price,
            order_type=order_type,
            limit_price=limit_price,
            stop_price=stop_price,
            time_in_force=time_in_force,
            asset_class=asset_class,
        )
    return live_sell(
        symbol=symbol,
        qty=qty,
        notional=notional,
        estimated_price=estimated_price,
        order_type=order_type,
        limit_price=limit_price,
        stop_price=stop_price,
        time_in_force=time_in_force,
        asset_class=asset_class,
    )


@mcp.tool()
def live_twap_order(
    symbol: str,
    side: str,
    qty: Optional[float] = None,
    notional: Optional[float] = None,
    estimated_price: Optional[float] = None,
    slices: Optional[int] = None,
    interval_seconds: Optional[int] = None,
    order_type: str = "market",
    limit_price: Optional[float] = None,
    stop_price: Optional[float] = None,
    time_in_force: Optional[str] = None,
    asset_class: str = "equity",
) -> Dict[str, Any]:
    side = side.lower()
    if side not in ("buy", "sell"):
        return {"error": "side must be buy or sell"}
    if qty is None and notional is None:
        return {"error": "Either qty or notional must be provided"}

    slice_count = slices or _get_env_int("TWAP_SLICES", 4)
    delay = interval_seconds or _get_env_int("TWAP_INTERVAL_SECONDS", 15)
    results = []

    if qty is not None:
        if asset_class == "equity":
            qty_slices = _split_equity_qty(qty, slice_count)
        else:
            qty_slices = [float(qty) / float(slice_count)] * slice_count
        for slice_qty in qty_slices:
            if side == "buy":
                result = live_buy(
                    symbol=symbol,
                    qty=slice_qty,
                    estimated_price=estimated_price,
                    order_type=order_type,
                    limit_price=limit_price,
                    stop_price=stop_price,
                    time_in_force=time_in_force,
                    asset_class=asset_class,
                )
            else:
                result = live_sell(
                    symbol=symbol,
                    qty=slice_qty,
                    estimated_price=estimated_price,
                    order_type=order_type,
                    limit_price=limit_price,
                    stop_price=stop_price,
                    time_in_force=time_in_force,
                    asset_class=asset_class,
                )
            results.append(result)
            if delay > 0:
                time.sleep(delay)
        return {"slices": len(results), "results": results}

    notional_slices = _split_notional(float(notional), slice_count)
    for slice_notional in notional_slices:
        if side == "buy":
            result = live_buy(
                symbol=symbol,
                notional=slice_notional,
                order_type=order_type,
                limit_price=limit_price,
                stop_price=stop_price,
                time_in_force=time_in_force,
                asset_class=asset_class,
            )
        else:
            result = live_sell(
                symbol=symbol,
                notional=slice_notional,
                order_type=order_type,
                limit_price=limit_price,
                stop_price=stop_price,
                time_in_force=time_in_force,
                asset_class=asset_class,
            )
        results.append(result)
        if delay > 0:
            time.sleep(delay)

    return {"slices": len(results), "results": results}


if __name__ == "__main__":
    port = int(os.getenv("LIVE_TRADE_HTTP_PORT", "8004"))
    mcp.run(transport="streamable-http", port=port)
