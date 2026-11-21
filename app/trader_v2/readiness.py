"""Read-only V2 readiness explanations from verified account observations.

These are not V1 order decisions: an ONLINE worker is not proof of tradability.
No credential, risk-policy, broker SDK, market-data or trade-journal writes.
"""
from __future__ import annotations

KNOWN_BROKERS=frozenset(("schwab","webull","robinhood_crypto","paper"))
KNOWN_MARKET=frozenset(("FRESH_READ_ONLY","FRESH_EXTERNAL_SIGNAL_ONLY",
                        "BROKER_ENDPOINTS_AUTHORIZED_NO_QUOTE_CACHE",
                        "BROKER_ENDPOINTS_PARTIAL_OR_RESTRICTED",
                        "QUOTE_UNVERIFIED","NO_FRESH_QUOTE","RECORDED_CANDLES_ONLY"))
GATES=("authentication","worker","account_observation","operator_permission",
       "market_data","technical_signal","ai_review","risk","order_reconciliation")
UNKNOWN="NOT_VERIFIED"
ACTIONS={
    "SCHWAB_REAUTH_REQUIRED":"Reconnect Schwab through Broker Connections",
    "BROKER_REAUTH_REQUIRED":"Reconnect the selected brokerage account",
    "WORKER_OFFLINE":"Inspect this broker's worker diagnostics",
    "BROKER_SNAPSHOT_UNVERIFIED":"Inspect authenticated balances and position freshness",
    "BROKER_NOT_ARMED":"Review this account's Risk & Start settings",
    "V2_MARKET_EXECUTION_UNVERIFIED":"Validate broker-executable quotes and market hours before V2 cutover",
    "V2_DATA_ONLY":"Run V2 paper/replay validation before enabling a new execution path",
}
def explain(account_rows,source_rows):
    """Return bounded public readiness gates; not a live order permission check."""
    if not isinstance(account_rows,list) or not isinstance(source_rows,dict):
        return []
    out=[]
    seen=set()
    for raw in account_rows[:10]:
        if not isinstance(raw,dict):continue
        broker=raw.get("broker")
        if not isinstance(broker,str) or broker not in KNOWN_BROKERS or broker in seen:continue
        seen.add(broker)
        auth=raw.get("auth")
        worker=raw.get("worker_state")
        verified=raw.get("read_verified") is True
        armed=raw.get("permission_armed") is True
        market=source_rows.get(broker) or {}
        market_state=market.get("state") if isinstance(market,dict) else None
        if not isinstance(market_state,str) or market_state not in KNOWN_MARKET:market_state=UNKNOWN
        states={name:UNKNOWN for name in GATES}
        if auth=="CONNECTED":states["authentication"]="PASS"
        elif auth in ("REAUTH_REQUIRED","DISABLED"):states["authentication"]="BLOCKED"
        if worker in ("ONLINE","PAPER_ONLY"):states["worker"]="PASS"
        elif worker=="OFFLINE":states["worker"]="BLOCKED"
        states["account_observation"]="PASS" if verified else UNKNOWN
        if broker!="paper":
            states["operator_permission"]="CONFIGURED" if armed else "BLOCKED"
        else:
            states["operator_permission"]=UNKNOWN
        # No Phase 2 market source proves executable brokerage quotes, spread
        # or live-session entitlement, even when the public feed is fresh.
        states["market_data"]="OBSERVED_NON_EXECUTABLE" if market_state in (
            "FRESH_READ_ONLY","FRESH_EXTERNAL_SIGNAL_ONLY") else UNKNOWN
        if auth=="REAUTH_REQUIRED":
            code="SCHWAB_REAUTH_REQUIRED" if broker=="schwab" else "BROKER_REAUTH_REQUIRED"
            classification="BLOCKED"
        elif auth=="DISABLED":
            code="BROKER_REAUTH_REQUIRED";classification="BLOCKED"
        elif worker=="OFFLINE":
            code="WORKER_OFFLINE";classification="BLOCKED"
        elif not verified:
            code="BROKER_SNAPSHOT_UNVERIFIED";classification=UNKNOWN
        elif broker!="paper" and not armed:
            code="BROKER_NOT_ARMED";classification="BLOCKED"
        elif market_state in ("FRESH_READ_ONLY","FRESH_EXTERNAL_SIGNAL_ONLY"):
            code="V2_DATA_ONLY";classification=UNKNOWN
        else:
            code="V2_MARKET_EXECUTION_UNVERIFIED";classification=UNKNOWN
        out.append({
            "broker":broker, "classification":classification,
            "first_issue":code,"user_action":ACTIONS[code],
            "last_verified_scan":None,
            "execution_path":"V2_READ_ONLY_NO_ORDER_AUTHORITY",
            "gates":states,
            "source_state":market_state,
        })
    return out
