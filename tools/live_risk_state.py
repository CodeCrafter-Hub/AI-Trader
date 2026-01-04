import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any


def _state_path() -> Path:
    base_dir = Path(__file__).resolve().parents[1]
    return base_dir / "data" / "live_state.json"


def load_state() -> Dict[str, Any]:
    path = _state_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state: Dict[str, Any]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def get_or_init_day_state(equity: float) -> Dict[str, Any]:
    today = datetime.utcnow().date().isoformat()
    state = load_state()
    day_state = state.get("daily", {})

    if day_state.get("date") != today:
        day_state = {
            "date": today,
            "equity_start": equity,
        }
        state["daily"] = day_state
        save_state(state)

    return day_state
