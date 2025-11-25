from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


@dataclass
class EquityPoint:
    date: str
    total_value: float
    missing_prices: List[str]


@dataclass
class PerformanceReport:
    equity_curve: List[EquityPoint]
    daily_returns: List[float]
    turnover: float
    metrics: Dict[str, float]
    missing_price_days: Dict[str, List[str]]
    missing_price_symbols: List[str]
    skipped_records: int


PRICE_FIELD = "4. close"
TRADING_DAYS_PER_YEAR = 252


def _load_price_series(symbol: str, price_dir: Path) -> Dict[str, Dict[str, str]]:
    file_path = price_dir / f"daily_prices_{symbol}.json"
    if not file_path.exists():
        return {}

    with file_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    series = data.get("Time Series (Daily)", {})
    return series if isinstance(series, dict) else {}


def _build_price_cache(symbols: Iterable[str], price_dir: Path) -> Dict[str, Dict[str, Dict[str, str]]]:
    cache: Dict[str, Dict[str, Dict[str, str]]] = {}
    for sym in symbols:
        series = _load_price_series(sym, price_dir)
        if series:
            cache[sym] = series
    return cache


def _get_price_for_date(symbol: str, date: str, price_cache: Dict[str, Dict[str, Dict[str, str]]]) -> Optional[float]:
    series = price_cache.get(symbol)
    if not series:
        return None

    def _extract_price(day: str) -> Optional[float]:
        bar = series.get(day)
        if not isinstance(bar, dict):
            return None
        raw_val = bar.get(PRICE_FIELD)
        try:
            return float(raw_val) if raw_val is not None else None
        except (TypeError, ValueError):
            return None

    # Try exact date first
    exact_price = _extract_price(date)
    if exact_price is not None:
        return exact_price

    # Fallback: look back up to 5 previous trading days
    current = datetime.strptime(date, "%Y-%m-%d").date()
    for _ in range(5):
        current -= timedelta(days=1)
        candidate = current.strftime("%Y-%m-%d")
        price = _extract_price(candidate)
        if price is not None:
            return price
    return None


def _load_position_records(position_file: Path) -> Tuple[List[dict], int]:
    position_records: List[dict] = []
    skipped = 0
    with position_file.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                continue
            if not isinstance(record, dict):
                skipped += 1
                continue
            position_records.append(record)
    return position_records, skipped


def _sorted_position_records(position_records: List[dict]) -> List[dict]:
    dated_records: List[Tuple[datetime, int, dict]] = []
    for idx, record in enumerate(position_records):
        date_str = record.get("date")
        if not date_str:
            continue
        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        except (TypeError, ValueError):
            continue
        dated_records.append((date_obj, idx, record))
    dated_records.sort(key=lambda item: (item[0], item[1]))
    return [rec for _, _, rec in dated_records]


def _compute_equity_curve(
    position_records: List[dict], price_cache: Dict[str, Dict[str, Dict[str, str]]]
) -> Tuple[List[EquityPoint], Dict[str, List[str]]]:
    equity_curve: List[EquityPoint] = []
    missing_price_days: Dict[str, List[str]] = {}

    for record in position_records:
        date = record.get("date")
        if not date:
            continue
        positions = record.get("positions", {})
        if not isinstance(positions, dict):
            continue
        missing: List[str] = []
        total_value = 0.0

        for symbol, amount in positions.items():
            if symbol == "CASH":
                try:
                    total_value += float(amount)
                except (TypeError, ValueError):
                    continue
                continue

            if not amount:
                continue

            price = _get_price_for_date(symbol, date, price_cache)
            if price is None:
                missing.append(symbol)
                continue

            try:
                total_value += float(amount) * price
            except (TypeError, ValueError):
                missing.append(symbol)

        equity_point = EquityPoint(date=date, total_value=total_value, missing_prices=missing)
        equity_curve.append(equity_point)
        if missing:
            missing_price_days[date] = missing

    return equity_curve, missing_price_days


def _compute_daily_returns(equity_curve: List[EquityPoint]) -> List[float]:
    returns: List[float] = []
    for prev, curr in zip(equity_curve, equity_curve[1:]):
        if prev.total_value <= 0:
            returns.append(0.0)
            continue
        returns.append((curr.total_value / prev.total_value) - 1)
    return returns


def _compute_turnover(position_records: List[dict], price_cache: Dict[str, Dict[str, Dict[str, str]]]) -> float:
    if len(position_records) < 2:
        return 0.0

    turnovers: List[float] = []
    for prev, curr in zip(position_records, position_records[1:]):
        prev_positions = prev.get("positions", {})
        curr_positions = curr.get("positions", {})
        date = curr.get("date")

        traded_value = 0.0
        for symbol, curr_amount in curr_positions.items():
            if symbol == "CASH":
                continue
            try:
                prev_amount = float(prev_positions.get(symbol, 0))
                curr_val = float(curr_amount)
            except (TypeError, ValueError):
                continue

            delta = curr_val - prev_amount
            if delta == 0:
                continue
            price = _get_price_for_date(symbol, date, price_cache)
            if price is None:
                continue
            traded_value += abs(delta) * price

        prev_value = 0.0
        for sym, amount in prev_positions.items():
            if sym == "CASH":
                try:
                    prev_value += float(amount)
                except (TypeError, ValueError):
                    continue
                continue

            price = _get_price_for_date(sym, prev.get("date"), price_cache)
            if price is None:
                continue
            try:
                prev_value += float(amount) * price
            except (TypeError, ValueError):
                continue

        if prev_value > 0:
            turnovers.append(traded_value / prev_value)

    if not turnovers:
        return 0.0
    return sum(turnovers) / len(turnovers)


def _max_drawdown(equity_curve: List[EquityPoint]) -> float:
    peak = -math.inf
    max_dd = 0.0
    for point in equity_curve:
        peak = max(peak, point.total_value)
        if peak <= 0:
            continue
        drawdown = (point.total_value / peak) - 1
        max_dd = min(max_dd, drawdown)
    return max_dd


def _annualized_volatility(daily_returns: List[float]) -> float:
    if not daily_returns:
        return 0.0
    mean_return = sum(daily_returns) / len(daily_returns)
    variance = sum((r - mean_return) ** 2 for r in daily_returns) / max(len(daily_returns) - 1, 1)
    return math.sqrt(variance) * math.sqrt(TRADING_DAYS_PER_YEAR)


def _annualized_return(daily_returns: List[float]) -> float:
    if not daily_returns:
        return 0.0
    compounded = 1.0
    for r in daily_returns:
        compounded *= (1 + r)
    periods = len(daily_returns)
    return compounded ** (TRADING_DAYS_PER_YEAR / periods) - 1 if periods else 0.0


def _sharpe_ratio(daily_returns: List[float]) -> float:
    volatility = _annualized_volatility(daily_returns)
    if volatility == 0:
        return 0.0
    return (sum(daily_returns) / len(daily_returns)) * TRADING_DAYS_PER_YEAR / volatility


def _sortino_ratio(daily_returns: List[float]) -> float:
    downside = [r for r in daily_returns if r < 0]
    if not downside:
        return float("inf") if daily_returns else 0.0
    downside_vol = _annualized_volatility(downside)
    if downside_vol == 0:
        return 0.0
    return (sum(daily_returns) / len(daily_returns)) * TRADING_DAYS_PER_YEAR / downside_vol


def build_performance_report(position_file: Path, price_dir: Path) -> Optional[PerformanceReport]:
    if not position_file.exists():
        return None

    position_records, skipped_records = _load_position_records(position_file)

    sorted_records = _sorted_position_records(position_records)
    if not sorted_records:
        return None

    symbols = set()
    for record in sorted_records:
        positions = record.get("positions", {})
        if not isinstance(positions, dict):
            continue
        for sym in positions:
            if sym != "CASH":
                symbols.add(sym)

    price_cache = _build_price_cache(sorted(symbols), price_dir)
    missing_price_symbols = sorted(sym for sym in symbols if sym not in price_cache)

    equity_curve, missing_price_days = _compute_equity_curve(sorted_records, price_cache)
    daily_returns = _compute_daily_returns(equity_curve)
    turnover = _compute_turnover(sorted_records, price_cache)

    start_value = equity_curve[0].total_value
    end_value = equity_curve[-1].total_value

    metrics = {
        "cumulative_return": (end_value / start_value - 1) if start_value else 0.0,
        "annualized_return": _annualized_return(daily_returns),
        "max_drawdown": _max_drawdown(equity_curve),
        "volatility": _annualized_volatility(daily_returns),
        "sharpe_ratio": _sharpe_ratio(daily_returns),
        "sortino_ratio": _sortino_ratio(daily_returns),
        "turnover": turnover,
        "start_value": start_value,
        "end_value": end_value,
    }

    return PerformanceReport(
        equity_curve=equity_curve,
        daily_returns=daily_returns,
        turnover=turnover,
        metrics=metrics,
        missing_price_days=missing_price_days,
        missing_price_symbols=missing_price_symbols,
        skipped_records=skipped_records,
    )
