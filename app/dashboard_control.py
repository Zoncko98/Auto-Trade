"""Atomic, validated control-plane document shared by GUI and paper worker.

Control file carries configuration only, NEVER brokerage credentials or orders.
A missing/invalid file disables strategy processing until deliberately started.
"""
from __future__ import annotations
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

MODES = ("running", "paused", "stopped")
DEFAULT_SETTINGS = {
    "allocation_pct": 100.0,
    "max_order_usd": 0.0,
    "max_position_pct": 25.0,
    "max_daily_loss": 5.0,
    "max_open_positions": 3,
    "reinvest_pct": 100.0,
    "daily_growth_target_pct": 0.7,
}
BOUNDS = {
    "allocation_pct": (0, 100),
    "max_order_usd": (0, 10000),
    "max_position_pct": (0.1, 50),
    "max_daily_loss": (0.01, 10000),
    "max_open_positions": (1, 10),
    "reinvest_pct": (0, 100),
    "daily_growth_target_pct": (0, 10),
}

def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def validated_settings(settings: dict) -> dict:
    if not isinstance(settings, dict) or set(settings) != set(DEFAULT_SETTINGS):
        raise ValueError("Settings must contain exactly the supported fields")
    out = {}
    for key, (low, high) in BOUNDS.items():
        value = settings[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{key} must be a number")
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"{key} must be between {low} and {high}")
        if key == "max_open_positions":
            if not isinstance(value, int):
                raise ValueError("max_open_positions must be an integer")
            out[key] = value
        else:
            out[key] = round(float(value), 4)
    return out

def default_control() -> dict:
    return {
        "version": 1, "revision": 0, "mode": "stopped",
        "settings": DEFAULT_SETTINGS.copy(), "updated_at": now_utc(),
    }

def checked_control(data: dict) -> dict:
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("Unsupported control document")
    if data.get("mode") not in MODES:
        raise ValueError("Invalid operation mode")
    rev = data.get("revision")
    if not isinstance(rev, int) or isinstance(rev, bool) or rev < 0:
        raise ValueError("Invalid revision")
    settings = validated_settings(data.get("settings"))
    return {
        "version": 1, "revision": rev, "mode": data["mode"],
        "settings": settings, "updated_at": str(data.get("updated_at", ""))[:45],
    }

def read_control(path: Path) -> dict:
    path = Path(path)
    if not path.exists():
        return default_control()
    return checked_control(json.loads(path.read_text(encoding="utf-8")))

def write_atomic(path: Path, payload: dict) -> None:
    path = Path(path)
    path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    data = json.dumps(payload, indent=2, allow_nan=False).encode("utf-8") + b"\n"
    fd, name = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            os.fchmod(f.fileno(), 0o600)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
