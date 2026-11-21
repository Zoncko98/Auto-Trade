"""Webull signed GET-only probe runner. No live V2 order authorization."""
from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
from .webull_migration_probe import probe_webull
from .recorded_replay import _atomic_json
from .readonly_adapters import private_json, time_seen


def result_status(state, *, now=None):
    now=now or datetime.now(timezone.utc)
    path=Path(state)/"v2/broker_migration/webull.json"
    doc=private_json(path,maximum=16000)
    stamp=time_seen(doc.get("checked_at"),now) if doc else None
    if not stamp:
        return {"state":"NOT_YET_VERIFIED_OR_STALE",
                "broker":"webull","live_order_authority":False,
                "cutover_ready":False,"first_blocker":"SIGNED_WEBULL_PREFLIGHT_REQUIRED"}
    return {
        **{key: value for key,value in doc.items() if key in (
            "schema","broker","checked_at","mode","first_blocker",
            "broker_account_verified","funding_verified",
            "settled_cash_verified","broker_positions_verified",
            "broker_open_orders_verified","broker_open_order_count",
            "local_order_count","local_unresolved_count",
            "signed_historical_fill_count","signed_historical_fills_verified",
            "v1_writer_handoff_verified","live_v2_orders_submitted")},
        "state":"FRESH_READ_ONLY_PREFLIGHT",
        "cutover_ready":False,"live_order_authority":False,
    }


def run_once(state, signed_broker=None, *, now=None):
    now=now or datetime.now(timezone.utc)
    if signed_broker is None:
        current=result_status(state,now=now)
        if current.get("state")=="FRESH_READ_ONLY_PREFLIGHT":
            return current
    target=Path(state)/"v2/broker_migration"
    if target.is_symlink():
        raise PermissionError("Unsafe migration journal")
    target.mkdir(mode=0o700,parents=True,exist_ok=True)
    if target.stat().st_mode&0o077:
        raise PermissionError("Migration journal permissions invalid")
    result={"schema":1,"broker":"webull","mode":"AUTHENTICATED_WEBULL_READ_ONLY",
            "checked_at":now.isoformat(),"live_order_authority":False,
            "cutover_ready":False,"first_blocker":"SIGNED_WEBULL_PREFLIGHT_UNAVAILABLE",
            "live_v2_orders_submitted":0}
    try:
        from webull_trade_config import read
        from webull_broker import WebullBroker
        policy=read(state)
        broker=signed_broker if signed_broker is not None else WebullBroker(state)
        result=probe_webull(state,broker,policy,now=now)
    except Exception:
        # Do not leak signer credentials or provider error bodies into the
        # persisted status/API. Only evidence-rejection codes are exposed.
        pass
    _atomic_json(target/"webull.json",result)
    return result
