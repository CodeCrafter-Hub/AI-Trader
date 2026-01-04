import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from integrations.alpaca_broker import AlpacaBroker


def _log_path() -> Path:
    base_dir = Path(__file__).resolve().parents[1]
    return base_dir / "data" / "live_runs.jsonl"


def _safe_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def record_run_summary(
    run_id: str,
    model_signature: str,
    status: str,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    broker = AlpacaBroker()
    account = {}
    positions = []
    try:
        account = broker.get_account()
    except Exception as exc:
        account = {"error": str(exc)}
    try:
        positions = broker.list_positions()
    except Exception as exc:
        positions = [{"error": str(exc)}]

    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "run_id": run_id,
        "model_signature": model_signature,
        "status": status,
        "account": account,
        "equity": _safe_float(account.get("equity")) if isinstance(account, dict) else None,
        "buying_power": _safe_float(account.get("buying_power")) if isinstance(account, dict) else None,
        "positions": positions,
        "details": details or {},
    }

    log_path = _log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
