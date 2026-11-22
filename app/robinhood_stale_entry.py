"""Bounded cancellation of old, *unfilled*, exact bot-owned Robinhood BUYs.

An existing GTC buy may block ALL new entries and protected exits indefinitely.
Cancel only on pre-existing autonomous account authorization, after signed
broker confirmation of zero fills and exact immutable client/broker order IDs.
Durably mark the original V1 journal BEFORE the signed cancellation POST.
No POST is retried: pending cancellation must be reconciled by original order.
"""
from __future__ import annotations
from datetime import datetime,timezone
from decimal import Decimal,InvalidOperation
from uuid import UUID
from robinhood_order_journal import OrderJournal,UnreconciledOrder
from robinhood_crypto_gateway import RobinhoodUnavailable
from trader_v2.writer_ownership import account_writer_scope,WriterOwnershipError

def _uuid(value):
    if not isinstance(value,str):return None
    try:
        obj=UUID(value)
        return str(obj) if str(obj)==value.lower() else None
    except (ValueError,TypeError,AttributeError):return None

def _age_minutes(value,now):
    if not isinstance(value,str):return None
    try:
        parsed=datetime.fromisoformat(value.replace("Z","+00:00"))
        if parsed.tzinfo is None:return None
        delta=(now-parsed.astimezone(timezone.utc)).total_seconds()/60
        return delta if 0<=delta<=525600 else None
    except (ValueError,TypeError,OverflowError):return None

def _zero_filled(row):
    raw=row.get("filled_asset_quantity")
    if isinstance(raw,bool) or raw is None:return False
    try:q=Decimal(str(raw))
    except (ValueError,InvalidOperation,TypeError):return False
    if not q.is_finite() or q!=0:return False
    executions=row.get("executions")
    return isinstance(executions,list) and not executions

def _reason(code,*,age=None):
    result={"state":code,"cancel_submitted":False,"broker_filled":False,
            "may_enter_new_order":False}
    if age is not None:result["age_minutes"]=int(age)
    return result

def reconcile_stale_entry(state,journal,policy,account,signed_orders,
                          *,now=None,trader_factory=None):
    """Attempt at most one broker CANCEL, never a new order submission.

    signed_orders must be the complete signed current broker order response,
    obtained by the existing authorized V1 worker. Not a cached dashboard
    file, order ID provided from the UI, or an arbitrary broker-side order.
    """
    now=now or datetime.now(timezone.utc)
    if not isinstance(now,datetime) or now.tzinfo is None:
        return _reason("STALE_BUY_CLOCK_UNVERIFIED")
    now=now.astimezone(timezone.utc)
    if (not isinstance(policy,dict) or policy.get("enabled") is not True or
        policy.get("account")!=account or not isinstance(account,str) or
        not account):
        return _reason("STALE_BUY_ACCOUNT_NOT_AUTHORIZED")
    limit=policy.get("stale_entry_cancel_minutes")
    if type(limit) is not int or not 0<=limit<=1440:
        return _reason("STALE_BUY_CANCELLATION_LIMIT_UNVERIFIED")
    if limit==0:return _reason("STALE_BUY_AUTO_CANCEL_DISABLED")
    if not isinstance(journal,OrderJournal) or not isinstance(signed_orders,list):
        return _reason("STALE_BUY_SIGNED_HISTORY_UNAVAILABLE")
    if any(not isinstance(item,dict) for item in signed_orders):
        return _reason("STALE_BUY_SIGNED_ORDER_ROW_UNVERIFIED")
    try:pending=journal.pending()
    except Exception:return _reason("STALE_BUY_LOCAL_JOURNAL_UNAVAILABLE")
    if not pending:return _reason("NO_UNRESOLVED_BOT_BUY")
    if len(pending)!=1:return _reason("MULTIPLE_UNRESOLVED_ORDERS")
    local=pending[0]
    if not isinstance(local,dict) or local.get("account")!=account:
        return _reason("OTHER_ACCOUNT_PENDING_ORDER")
    # Original durable cancel-request timestamp survives even when an
    # older journal reconciler normalizes an OPEN state back to submitted.
    # A post-timeout or worker restart can NEVER cause a second cancel POST.
    if local.get("status")=="cancel_requested" or local.get("cancel_requested_at"):
        return _reason("STALE_BUY_CANCEL_ALREADY_REQUESTED")
    if local.get("status")!="submitted_unconfirmed" or local.get("side")!="buy":
        return _reason("STALE_BUY_NOT_ELIGIBLE")
    age=_age_minutes(local.get("created_at"),now)
    if age is None:return _reason("STALE_BUY_CREATED_TIME_UNVERIFIED")
    if age<limit:return _reason("STALE_BUY_STILL_WITHIN_LIMIT",age=age)
    cid=_uuid(local.get("client_order_id"))
    broker_id=_uuid(local.get("broker_order_id"))
    if not cid or not broker_id:
        return _reason("STALE_BUY_ORIGINAL_BROKER_ORDER_ID_UNVERIFIED",age=age)
    matching=[item for item in signed_orders if
              item.get("client_order_id")==cid]
    if len(matching)!=1:
        return _reason("STALE_BUY_EXACT_SIGNED_ORDER_NOT_FOUND",age=age)
    signed=matching[0]
    if (_uuid(signed.get("id"))!=broker_id or
        (signed.get("account_number") is not None and
         signed["account_number"]!=account) or
        signed.get("side")!="buy"):
        return _reason("STALE_BUY_BROKER_IDENTITY_MISMATCH",age=age)
    broker_state=str(signed.get("state",signed.get("status",""))).lower()
    if broker_state!="open":
        return _reason("STALE_BUY_BROKER_NOT_OPEN",age=age)
    if not _zero_filled(signed):
        return _reason("STALE_BUY_ZERO_FILL_NOT_CONFIRMED",age=age)
    # Same durable V1/V2 exclusive writer lock used at the actual order POST.
    # The original bot intent remains pending until a signed broker GET
    # confirms cancellation or final fill; a network failure never clears it.
    try:
        with account_writer_scope(state,"robinhood_crypto",account,owner="V1"):
            # Re-check original pending state INSIDE the account owner lock.
            current=journal.pending()
            if len(current)!=1 or current[0].get("client_order_id")!=cid or (
                  current[0].get("status")!="submitted_unconfirmed"):
                return _reason("STALE_BUY_JOURNAL_CHANGED",age=age)
            if trader_factory is None:
                from robinhood_crypto_execution import RobinhoodCryptoTradingAdapter
                trader_factory=RobinhoodCryptoTradingAdapter.from_state_authorized
            trader=trader_factory(state,policy)
            if not callable(getattr(trader,"cancel_order",None)):
                return _reason("STALE_BUY_CANCEL_ADAPTER_UNAVAILABLE",age=age)
            journal.mark_cancel_requested(account,cid,broker_id,now=now)
            try:
                trader.cancel_order(account,broker_id)
            except Exception:
                # Signed cancel POST may have been accepted before the error.
                # NEVER retry. Only signed next-cycle GET can end this state.
                return _reason("STALE_BUY_CANCEL_OUTCOME_UNCERTAIN",age=age)
        answer=_reason("STALE_BUY_CANCEL_REQUESTED_AWAIT_BROKER",age=age)
        answer["cancel_submitted"]=True
        return answer
    except (UnreconciledOrder,WriterOwnershipError,OSError,ValueError,TypeError):
        return _reason("STALE_BUY_CANCEL_NOT_AUTHORIZED",age=age)
