"""Production V2 launch safety gate: identify each missing broker acceptance boundary.

Read-only. Never authorizes a handoff, starts an order writer, or infers
broker settlement/session state from buying power or local file existence.
Source is the independently signed cached broker GET preflight; it expires.
"""
from __future__ import annotations
from datetime import datetime,timezone
from pathlib import Path
from .readonly_adapters import private_json
from .conservative_risk_map import mapping

BROKERS=("robinhood_crypto","webull","schwab")
TTL_SECONDS=1200

def _true(value):
    return value is True

def _observed(doc,now):
    if not isinstance(doc,dict):return False
    raw=doc.get("checked_at")
    if not isinstance(raw,str):return False
    try:
        t=datetime.fromisoformat(raw.replace("Z","+00:00"))
        if t.tzinfo is None:return False
        age=(now-t.astimezone(timezone.utc)).total_seconds()
        return -2<=age<=TTL_SECONDS
    except (ValueError,TypeError,OverflowError):
        return False

def _check(name,ok,reason):
    return {"name":name,"verified":ok is True,
            "blocker":None if ok is True else reason}

def launch_status(state_dir,broker,*,now=None):
    """Explain *all* cutover gates, not just the first local V1 issue."""
    if broker not in BROKERS:raise ValueError("Unsupported broker")
    now=now or datetime.now(timezone.utc)
    if not isinstance(now,datetime) or now.tzinfo is None:
        raise ValueError("Expected aware UTC observation")
    root=Path(state_dir)
    probe=private_json(root/"v2"/"broker_migration"/(broker+".json"),maximum=16000)
    expected_mode=({"robinhood_crypto":"AUTHENTICATED_SIGNED_READ_ONLY",
                    "webull":"AUTHENTICATED_WEBULL_READ_ONLY"}.get(broker))
    fresh=bool(expected_mode and _observed(probe,now) and
               probe.get("broker")==broker and probe.get("mode")==expected_mode)
    signed=probe if fresh else {}
    risk=mapping(root,broker)
    if broker=="robinhood_crypto":
        account_ok=_true(signed.get("account_verified"))
        holdings=_true(signed.get("holdings_verified"))
        history=_true(signed.get("broker_history_verified")) and _true(signed.get("local_journal_matched"))
        quote=(type(signed.get("quote_timestamp_verified_symbols")) is int and signed["quote_timestamp_verified_symbols"]>0) or (
            type(signed.get("independent_trade_crosscheck_symbols")) is int and signed["independent_trade_crosscheck_symbols"]>0)
        open_orders=signed.get("broker_open_order_count")
        unresolved=signed.get("local_unresolved_count")
        pair_ok=type(signed.get("pairs_checked")) is int and signed["pairs_checked"]>0
    elif broker=="webull":
        account_ok=_true(signed.get("broker_account_verified"))
        # Webull currently confirms signed position response, NOT complete
        # product-specific holdings reconciliation.
        holdings=_true(signed.get("broker_positions_verified"))
        history=_true(signed.get("signed_historical_fills_verified"))
        quote=False
        open_orders=signed.get("broker_open_order_count")
        unresolved=signed.get("local_unresolved_count")
        pair_ok=False
    else:
        # Schwab has no equivalent signed account migration probe yet.
        account_ok=holdings=history=quote=pair_ok=False
        open_orders=unresolved=None
    orders_ok=(type(open_orders) is int and open_orders==0 and
               type(unresolved) is int and unresolved==0)
    gates=[
        _check("SIGNED_PREFLIGHT_FRESH",fresh,"SIGNED_BROKER_PREFLIGHT_STALE_OR_MISSING"),
        _check("SIGNED_ACCOUNT",account_ok,"SIGNED_ACCOUNT_NOT_VERIFIED"),
        _check("SIGNED_HOLDINGS",holdings,"SIGNED_PORTFOLIO_RECONCILIATION_REQUIRED"),
        _check("SIGNED_ORDER_HISTORY",history,"SIGNED_V1_ORDER_RECONCILIATION_REQUIRED"),
        _check("NO_OPEN_OR_UNRESOLVED_ORDERS",orders_ok,"BROKER_OR_LOCAL_PENDING_ORDERS"),
        _check("BROKER_PRODUCT_PERMISSIONS",pair_ok,"BROKER_TRADING_PAIR_OR_SYMBOL_PERMISSIONS_REQUIRED"),
        _check("EXECUTABLE_BROKER_QUOTE",quote,"SIGNED_EXECUTABLE_QUOTE_NOT_VERIFIED"),
        _check("V1_SAVED_NUMERIC_RISK",risk.get("state")=="SAVED_V1_NUMERIC_LIMITS_VALIDATED",
               "V1_RISK_SETTINGS_INCOMPATIBLE_OR_MISSING"),
        _check("SIGNED_SETTLED_FUNDING",False,"SIGNED_SETTLEMENT_NOT_CERTIFIED"),
        _check("SIGNED_MARKET_SESSION",False,"BROKER_SESSION_ENTITLEMENT_NOT_CERTIFIED"),
        _check("V1_AI_AND_EXIT_PARITY",False,"V2_AI_EXIT_AND_COOLDOWN_POLICY_INCOMPLETE"),
        _check("V1_WORKER_STOPPED",False,"ACCOUNT_SCOPED_V1_WORKER_STOP_NOT_VERIFIED"),
        _check("V2_SUPERVISOR_AND_RECONCILIATION",False,"LIVE_V2_WORKER_NOT_REGISTERED"),
        _check("EXCLUSIVE_WRITER_OWNERSHIP",False,"V1_TO_V2_HANDOFF_NOT_PERFORMED"),
        _check("SIGNED_BROKER_ACCEPTANCE",False,"BROKER_LIVE_ORDER_ACCEPTANCE_NOT_TESTED"),
    ]
    failures=[g["blocker"] for g in gates if not g["verified"]]
    return {
      "broker":broker,
      "mode":"LIVE_CUTOVER_GATED_READ_ONLY",
      "state":"BLOCKED" if failures else "READY",
      "live_v2_order_authority":False,
      "signed_observation_fresh":fresh,
      "gates":gates,
      "first_blocker":failures[0] if failures else None,
      "blockers":failures,
      "broker_order_submitted":False,
    }

def all_launch_status(state_dir,*,now=None):
    return {"stage":"LIVE_V2_CUTOVER_NOT_YET_ACCEPTED",
            "ready_accounts":0,
            "accounts":[launch_status(state_dir,b,now=now) for b in BROKERS]}
