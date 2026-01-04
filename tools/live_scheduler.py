import asyncio
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from integrations.alpaca_broker import AlpacaBroker
from main import main as run_main


def _env_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None or raw == "":
        return default
    return raw.lower() in ("1", "true", "yes", "on")


def _env_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _lock_path() -> Path:
    base_dir = Path(__file__).resolve().parents[1]
    return base_dir / "data" / "live_scheduler.lock"


def _acquire_lock(ttl_seconds: int) -> bool:
    lock_path = _lock_path()
    now = time.time()
    if lock_path.exists():
        try:
            last = float(lock_path.read_text(encoding="utf-8").strip())
        except Exception:
            last = 0.0
        if now - last < ttl_seconds:
            return False
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(str(now), encoding="utf-8")
    return True


def _release_lock() -> None:
    lock_path = _lock_path()
    if lock_path.exists():
        lock_path.unlink()


def _equity_market_open(broker: AlpacaBroker) -> Optional[bool]:
    try:
        clock = broker.get_clock()
    except Exception:
        return None
    return bool(clock.get("is_open"))


async def _run_once(config_path: str) -> None:
    await run_main(config_path)


def main() -> None:
    config_path = os.getenv("LIVE_CONFIG_PATH", "configs/live_config.json")
    interval = _env_int("LIVE_SCHEDULER_INTERVAL_SECONDS", 60)
    equity_open_only = _env_bool("LIVE_EQUITY_OPEN_ONLY", True)
    crypto_enabled = _env_bool("LIVE_CRYPTO_ENABLED", True)
    run_on_startup = _env_bool("LIVE_RUN_ON_STARTUP", True)
    lock_ttl = _env_int("LIVE_RUN_LOCK_TTL_SECONDS", max(120, interval * 2))

    broker = AlpacaBroker()

    if run_on_startup:
        if _acquire_lock(lock_ttl):
            try:
                asyncio.run(_run_once(config_path))
            finally:
                _release_lock()

    while True:
        should_run = True
        if equity_open_only and not crypto_enabled:
            market_open = _equity_market_open(broker)
            if market_open is False:
                should_run = False
        if should_run:
            if _acquire_lock(lock_ttl):
                try:
                    asyncio.run(_run_once(config_path))
                finally:
                    _release_lock()
        time.sleep(interval)


if __name__ == "__main__":
    main()
