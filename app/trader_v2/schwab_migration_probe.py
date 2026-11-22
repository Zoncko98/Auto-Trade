"""Schwab account V2 migration preflight using the EXISTING signed V1 client.

Called as a side-effect-isolated read-only diagnostic from the current V1
worker. No new OAuth client, no additional credential writer, no broker POST,
no journal editing, no account handoff. Every field is redacted evidence.
"""
from __future__ import annotations
from datetime import datetime,timezone
from decimal import Decimal
from pathlib import Path
import os

from .models import utc
from .readonly_adapters import private_json
from .recorded_replay import _atomic_json

_TERMINAL=frozenset(("FILLED","CANCELED","REJECTED","EXPIRED","REPLACED"))

def _report(now):
    return {"schema":1,"broker":"schwab","mode":"AUTHENTICATED_SCHWAB_READ_ONLY",
       "checked_at":now.isoformat(),"account_verified":False,
       "holdings_verified":False,"broker_history_verified":False,
       "local_journal_matched":False,"broker_open_order_count":None,
       "local_unresolved_count":None,"signed_settled_cash_verified":False,
       "broker_session_verified":False,"broker_product_verified":False,
       "quote_timestamp_verified_symbols":0,"historical_orders_checked":0,
       "first_blocker":"SCHWAB_SIGNED_ACCOUNT_NOT_VERIFIED",
       "cutover_ready":False,"v2_live_order_authority":False,
       "v2_live_orders_submitted":0}

def probe_schwab(state_dir,client,selected_hash,*,now=None):
    """Pure broker GET+private local read; no state writes or credential copying."""
    from live_worker import (
        confirm_account, current_broker_orders, broker_order_id,
        market_is_normal, result
    )
    from live_order_safety import position_snapshot,verified_cash,equity_value,quote_levels
    now=utc(now or datetime.now(timezone.utc))
    out=_report(now)
    if not isinstance(selected_hash,str) or not selected_hash:
        out["first_blocker"]="SCHWAB_SELECTED_ACCOUNT_REQUIRED"
        return out
    try:
        account=confirm_account(client,selected_hash)
        out["account_verified"]=True
        positions,exposure=position_snapshot(account)
        equity=equity_value(account)
        cash=verified_cash(account)
        if equity<0 or exposure<0 or cash<0 or equity+Decimal("0.01")<exposure:
            raise ValueError("Inconsistent account values")
        out["holdings_verified"]=True
        out["broker_position_symbols_checked"]=len(positions)
        sec=account.get("securitiesAccount",{})
        balances=sec.get("currentBalances",{})
        # Schwab margin-enabled accounts may still trade cash-only. However
        # cash AVAILABLE or buying power alone cannot attest settled funds.
        if ("unsettledCash" in balances and "pendingDeposits" in balances
            and Decimal(str(balances["unsettledCash"]))==0
            and Decimal(str(balances["pendingDeposits"]))==0 and cash>0):
            out["signed_settled_cash_verified"]=True
    except Exception:
        out["first_blocker"]=("SCHWAB_SIGNED_ACCOUNT_NOT_VERIFIED" if
              not out["account_verified"] else "SCHWAB_SIGNED_PORTFOLIO_OR_CASH_UNVERIFIED")
        return out
    try:
        # Signed broker GET history is complete only if the server did not hit
        # the 100-row bound; never treat the truncated page as all orders.
        signed=current_broker_orders(client,selected_hash)
        indexed={}
        broker_open=0
        for order in signed:
            if not isinstance(order,dict):
                raise ValueError("Malformed order")
            ident=broker_order_id(order)
            if ident in indexed:raise ValueError("Duplicate broker order")
            status=order.get("status")
            from live_order_safety import OPEN_STATUSES
            if status not in _TERMINAL|OPEN_STATUSES:
                raise ValueError("Unrecognized broker order state")
            if status not in _TERMINAL:broker_open+=1
            indexed[ident]=order
        out["broker_open_order_count"]=broker_open
        out["broker_history_verified"]=True
        doc=private_json(Path(state_dir)/"live"/"orders.json",maximum=4000000)
        if not isinstance(doc,dict) or doc.get("version")!=1 or doc.get("halted") is not False:
            raise ValueError("V1 journal missing or halted")
        local=doc.get("orders")
        if not isinstance(local,list) or len(local)>20000:
            raise ValueError("Invalid V1 order journal")
        unresolved=0
        matched=0
        for entry in local:
            if not isinstance(entry,dict):raise ValueError("Invalid local order")
            stage=entry.get("state")
            if stage not in _TERMINAL:
                unresolved+=1
                continue
            ident=entry.get("order_id")
            # An unsubmitted historical local canceled order can be an
            # explicit local cancellation; it is not broker history proof.
            if not isinstance(ident,(int,str)) or not str(ident).isdigit():
                raise ValueError("Terminal intent without a signed broker id")
            remote=indexed.get(str(ident))
            if not isinstance(remote,dict) or remote.get("status")!=stage:
                raise ValueError("Historical order state discrepancy")
            if stage=="FILLED":
                quantity=Decimal(str(remote.get("filledQuantity")))
                if not quantity.is_finite() or quantity!=Decimal(str(entry.get("quantity"))):
                    raise ValueError("Historical fill quantity discrepancy")
            matched+=1
        out["local_unresolved_count"]=unresolved
        out["historical_orders_checked"]=matched
        out["local_journal_matched"]=True
        if broker_open or unresolved:
            out["first_blocker"]="SCHWAB_OPEN_OR_UNRESOLVED_ORDERS"
            return out
    except Exception:
        out["first_blocker"]="SCHWAB_SIGNED_ORDER_HISTORY_OR_LOCAL_JOURNAL_UNVERIFIED"
        return out
    try:
        session=market_is_normal(client,now)
        out["broker_session_verified"]=session is True
    except Exception:
        out["broker_session_verified"]=False
    if out["broker_session_verified"]:
        try:
            # A signed, liquid stock quote with venue timestamp certifies a
            # market observation, NOT the ability to submit a V2 live order.
            payload=result(client.get_quote("SPY"),"signed stock quote")
            quote=payload.get("SPY") if isinstance(payload,dict) else None
            quote_levels(quote,now)
            out["broker_product_verified"]=True
            out["quote_timestamp_verified_symbols"]=1
        except Exception:
            pass
    if not out["signed_settled_cash_verified"]:
        out["first_blocker"]="SCHWAB_SETTLED_CASH_NOT_CERTIFIED"
    elif not out["broker_session_verified"]:
        out["first_blocker"]="SCHWAB_MARKET_SESSION_NOT_OPEN_OR_UNVERIFIED"
    elif not out["broker_product_verified"]:
        out["first_blocker"]="SCHWAB_SIGNED_EXECUTABLE_QUOTE_UNVERIFIED"
    else:
        out["first_blocker"]="SCHWAB_EXCLUSIVE_V1_V2_HANDOFF_AND_PARITY_REQUIRED"
    return out

def run_once(state_dir,client,selected_hash,*,now=None):
    """Persist owner-only redacted GET observations while leaving V1 in control."""
    root=Path(state_dir)
    at=utc(now or datetime.now(timezone.utc))
    report=probe_schwab(root,client,selected_hash,now=at)
    target=root/"v2"/"broker_migration"
    if target.is_symlink():raise PermissionError("Unsafe migration path")
    target.mkdir(mode=0o700,parents=True,exist_ok=True)
    if target.stat().st_mode&0o077:raise PermissionError("Unsafe migration permissions")
    _atomic_json(target/"schwab.json",report)
    return report
