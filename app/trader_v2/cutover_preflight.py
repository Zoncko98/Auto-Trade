"""Read-only V2 live-account migration preflight; never grants order authority.

It inspects existing PRIVATE state but never calls broker SDKs, touches a
credential/token, changes V1 risk configuration, or places an order.
A healthy account is NOT equivalent to a cutover-ready executor.
"""
from __future__ import annotations
from datetime import datetime,timezone
from decimal import Decimal,InvalidOperation
from pathlib import Path
from .readonly_adapters import private_json
from .risk_envelopes import envelope
from .conservative_risk_map import mapping
from .legacy_journal_audit import observe_legacy_journal
from .session_observation import session_observation

BROKERS=("schwab","webull","robinhood_crypto","paper")
_TERMINAL=frozenset(("FILLED","CANCELED","REJECTED","EXPIRED","REPLACED"))
LIMITS={
 "schwab":("max_order_usd","max_daily_loss","max_open_positions",
           "strategy_capital_usd","max_orders_per_day"),
 "webull":("max_order_usd","max_daily_loss_usd","max_open_positions",
           "max_total_exposure_usd"),
 "robinhood_crypto":("max_order_usd","max_daily_loss_usd",
                      "max_open_positions","max_total_exposure_usd"),
}
PATHS={
 "schwab":"live/risk_settings.json",
 "webull":"webull/risk_plan.json",
 "robinhood_crypto":"robinhood/risk_policy.json",
}

def _number(value):
    if value is None or isinstance(value,bool) or not isinstance(value,(str,int,float,Decimal)):
        return None
    try: n=Decimal(str(value))
    except (InvalidOperation,ValueError,TypeError):return None
    if not n.is_finite() or n<0 or n>1_000_000_000:
        return None
    return str(n)

def _limits(root,broker):
    doc=private_json(root/PATHS[broker],maximum=80000)
    if not doc:return {"state":"RISK_POLICY_UNAVAILABLE","source":PATHS[broker],"limits":{}}
    if broker=="schwab":
        if doc.get("version")!=1 or not isinstance(doc.get("settings"),dict):
            return {"state":"RISK_POLICY_INVALID","source":PATHS[broker],"limits":{}}
        values=doc["settings"]
    elif broker=="webull":
        values=doc.get("settings",doc)
        if not isinstance(values,dict):
            return {"state":"RISK_POLICY_INVALID","source":PATHS[broker],"limits":{}}
    else:
        values=doc
    clean={}
    for name in LIMITS[broker]:
        if name in values:
            value=_number(values.get(name))
            if value is None:
                return {"state":"RISK_POLICY_INVALID","source":PATHS[broker],"limits":{}}
            clean[name]=value
    return {"state":"RECORDED_V1_LIMITS_NOT_V2_AUTHORITY" if clean else "RISK_LIMITS_UNVERIFIED",
            "source":PATHS[broker],"limits":clean}

def _schwab_journal(root):
    doc=private_json(root/"live/orders.json",maximum=2_000_000)
    if not isinstance(doc,dict) or doc.get("version")!=1 or not isinstance(doc.get("orders"),list):
        return {"state":"JOURNAL_UNVERIFIED","records":None,"unresolved":None}
    orders=doc["orders"]
    if len(orders)>20000 or doc.get("halted") is True:
        return {"state":"HALTED_OR_OVERSIZED","records":min(len(orders),20000),
                "unresolved":None}
    states=[]
    for item in orders:
        if not isinstance(item,dict) or not isinstance(item.get("state"),str):
            return {"state":"JOURNAL_UNVERIFIED","records":len(orders),
                    "unresolved":None}
        state=item["state"].upper()
        if len(state)>50:
            return {"state":"JOURNAL_UNVERIFIED","records":len(orders),
                    "unresolved":None}
        states.append(state)
    unresolved=sum(s not in _TERMINAL for s in states)
    return {"state":"LOCAL_INTENTS_UNRESOLVED" if unresolved else "LOCAL_TERMINAL_ONLY",
            "records":len(orders),"unresolved":unresolved,
            "broker_reconciliation_verified":False}

def _other_journal(root,broker):
    # An observed broker status alone cannot establish complete authoritative
    # order reconciliation for V2 cutover. V1 journal schemas still differ.
    local=observe_legacy_journal(root,broker)
    if broker=="webull":
        worker=private_json(root/"webull/worker_status.json",maximum=1_500_000)
        block=worker.get("reconciliation") if isinstance(worker,dict) else None
        present=isinstance(block,(dict,list))
        return {"state":"V1_RECONCILIATION_OBSERVED_V2_UNVERIFIED" if present else
                "BROKER_RECONCILIATION_UNVERIFIED",
                "records":None,"unresolved":local["local_unresolved_count"],
                "local_evidence":local,
                "broker_reconciliation_verified":False}
    worker=private_json(root/"robinhood/worker_status.json",maximum=1_500_000)
    history=worker.get("broker_order_history_status") if isinstance(worker,dict) else None
    return {"state":"BROKER_HISTORY_OBSERVED_V2_UNVERIFIED" if history=="VERIFIED" else
            "BROKER_HISTORY_UNVERIFIED",
            "records":None,"unresolved":local["local_unresolved_count"],
            "local_evidence":local,
            "broker_reconciliation_verified":False}

def preflight(state_dir,account_rows,market_sources):
    """No writes; returns four bounded redacted account reports."""
    root=Path(state_dir)
    by_broker={r["broker"]:r for r in account_rows if
               isinstance(r,dict) and isinstance(r.get("broker"),str)
               and r["broker"] in BROKERS}
    sources=market_sources if isinstance(market_sources,dict) else {}
    reports=[]
    for broker in BROKERS:
        account=by_broker.get(broker,{})
        auth=account.get("auth")
        worker=account.get("worker_state")
        verified=account.get("read_verified") is True
        market=sources.get(broker)
        market_state=market.get("state") if isinstance(market,dict) else "NOT_VERIFIED"
        if not isinstance(market_state,str) or len(market_state)>70:
            market_state="NOT_VERIFIED"
        if broker=="paper":
            reports.append({"broker":broker,"stage":"SIMULATED_ONLY",
                "live_order_authority":False,"ready_for_v2_live":False,
                "first_blocker":"NO_LIVE_ADAPTER_BY_DESIGN",
                "risk":{"state":"PAPER_SEPARATE_ACCOUNT","limits":{}},
                "journal":{"state":"SEPARATE_SIMULATED_JOURNALS"},
                "source_state":market_state,"v1_writer_active":False})
            continue
        risk=_limits(root,broker)
        session=session_observation(broker)
        budget=envelope(root,broker,account)
        risk_map=mapping(root,broker) # Saved V1 only, never signed account authority.
        journal=(_schwab_journal(root) if broker=="schwab"
                 else _other_journal(root,broker))
        v1_writer_active=worker=="ONLINE"
        if auth=="REAUTH_REQUIRED":
            blocker="BROKER_REAUTH_REQUIRED"
        elif auth!="CONNECTED" or worker!="ONLINE" or not verified:
            blocker="VERIFIED_ACCOUNT_OR_WORKER_REQUIRED"
        elif journal["state"] in ("HALTED_OR_OVERSIZED","LOCAL_INTENTS_UNRESOLVED"):
            blocker="RECONCILIATION_REQUIRED"
        elif broker!="schwab" and journal.get("local_evidence",{}).get(
                "state")=="LOCAL_INTENTS_UNRESOLVED":
            blocker="RECONCILIATION_REQUIRED"
        elif broker!="schwab" and journal.get("local_evidence",{}).get(
                "state") not in ("LOCAL_TERMINAL_RECORDS_ONLY","LOCAL_JOURNAL_EMPTY"):
            blocker="LOCAL_JOURNAL_VERIFICATION_REQUIRED"
        elif journal["state"] in ("JOURNAL_UNVERIFIED","BROKER_RECONCILIATION_UNVERIFIED",
                                "BROKER_HISTORY_UNVERIFIED"):
            blocker="ORDER_JOURNAL_VERIFICATION_REQUIRED"
        elif v1_writer_active:
            blocker="V1_ORDER_WRITER_MUST_BE_PAUSED_FOR_CUTOVER"
        elif market_state not in ("FRESH_READ_ONLY","FRESH_EXTERNAL_SIGNAL_ONLY"):
            blocker="VERIFIED_MARKET_SOURCE_REQUIRED"
        else:
            blocker="V2_LIVE_EXECUTOR_NOT_ENABLED"
        reports.append({
            "broker":broker,"stage":"V1_LIVE_V2_SHADOW",
            "live_order_authority":False,"ready_for_v2_live":False,
            "first_blocker":blocker,
            "authentication":"CONNECTED" if auth=="CONNECTED" else (
                "REAUTH_REQUIRED" if auth=="REAUTH_REQUIRED" else "NOT_VERIFIED"),
            "account_verified":verified,
            "v1_writer_active":v1_writer_active,
            "v1_permission_configured":account.get("permission_armed") is True,
            "source_state":market_state,
            "executable_quote_verified":False,
            "market_session":session,
            "risk":risk,"risk_envelope":budget,
            "v2_risk_mapping":{"state":risk_map["state"],
                "v2_live_order_authorized":False,
                "requirements_unmapped":risk_map["unmapped_controls"]},
            "journal":journal,
            "requirements_remaining":[
                "SOURCE_AND_SESSION_EXECUTABILITY",
                "ACCOUNT_SPECIFIC_V2_RISK_MAPPING",
                "CANONICAL_ORDER_RECONCILIATION",
                "V1_WRITER_HANDOFF",
                "V2_BROKER_EXECUTOR_INTEGRATION",
                "BROKER_ACCEPTANCE_AND_FILL_VERIFICATION"],
        })
    return {"mode":"READ_ONLY_V2_LIVE_CUTOVER_PREFLIGHT",
            "live_order_authority":False,
            "automatic_cutover_allowed":False,
            "accounts":reports}
