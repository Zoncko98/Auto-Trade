"""Authenticated Webull V2 migration preflight; READ-ONLY signed GETs only.

This runs only when requested by an authorized operator and never changes V1
writer state, submits/cancels an order, or infers that buying power is settled
cash. Output is an intentionally redacted diagnostic, not an ownership lease.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import sqlite3
import re
from .webull_settlement import signed_settled_cash_budget
from .webull_signed_receipts import (
    WebullReceiptUnverified, client_order_id, normalize_webull_order,
)


def _money(raw, field):
    if type(raw) not in (str, int, Decimal):
        raise WebullReceiptUnverified(field + "_TYPE_UNVERIFIED")
    try:
        result = Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError):
        raise WebullReceiptUnverified(field + "_INVALID") from None
    if not result.is_finite() or result < 0 or result.adjusted() > 14:
        raise WebullReceiptUnverified(field + "_INVALID")
    return result


def _local_rows(root, account):
    """Read an existing Webull journal without creating or modifying it."""
    from .legacy_journal_audit import _safe_file
    target = Path(root) / "webull" / "orders.sqlite3"
    if not _safe_file(target, 30_000_000):
        raise WebullReceiptUnverified("LOCAL_WEBULL_JOURNAL_UNAVAILABLE")
    uri = "file:" + str(target.absolute()) + "?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=3) as db:
            db.execute("PRAGMA query_only=ON")
            rows = db.execute(
                "SELECT client_id,status,quantity,filled_qty,filled_price,fee,"
                "broker_id,side,asset,symbol FROM orders WHERE account=? "
                "ORDER BY created_at,client_id LIMIT 151", (account,)
            ).fetchall()
    except sqlite3.Error:
        raise WebullReceiptUnverified("LOCAL_WEBULL_JOURNAL_SCHEMA_UNVERIFIED") from None
    if len(rows) > 150:
        raise WebullReceiptUnverified("LOCAL_WEBULL_JOURNAL_REQUIRES_PAGINATION")
    return [dict(zip(("client_id","status","quantity","filled_qty","filled_price",
                      "fee","broker_id","side","asset","symbol"), row)) for row in rows]


def _signed_stock_positions(positions):
    # V2 stock orders must account for every signed holding, including external
    # inventory. No journal data can replace the current broker response.
    if not isinstance(positions,list):
        raise WebullReceiptUnverified("WEBULL_POSITIONS_NOT_LIST")
    signed={}
    for row in positions:
        if not isinstance(row,dict) or row.get("instrument_type")!="EQUITY":
            raise WebullReceiptUnverified("WEBULL_UNSUPPORTED_SIGNED_POSITION")
        sym=row.get("symbol")
        if not isinstance(sym,str) or not re.fullmatch(r"[A-Z][A-Z0-9.]{0,9}",sym) or sym in signed:
            raise WebullReceiptUnverified("WEBULL_POSITION_SYMBOL_UNVERIFIED")
        qty=_money(row.get("quantity"),"WEBULL_HELD_QUANTITY")
        if qty!=qty.to_integral_value():
            raise WebullReceiptUnverified("WEBULL_FRACTIONAL_POSITION_UNSUPPORTED")
        short=row.get("short_quantity")
        if short is not None and _money(short,"WEBULL_SHORT_QUANTITY")!=0:
            raise WebullReceiptUnverified("WEBULL_SHORT_POSITION_UNSUPPORTED")
        signed[sym]=qty
    return signed


def _legacy_bot_inventory(rows,signed):
    # All local fills must first have been matched to exact signed receipts.
    # Local inventory is a SUBSET of brokerage inventory; external holdings
    # are included in exposure, never silently adopted as bot-owned.
    bot={}
    for row in rows:
        if row["status"]!="FILLED":continue
        sym=row.get("symbol")
        if (row.get("asset")!="EQUITY" or not isinstance(sym,str)
                or not re.fullmatch(r"[A-Z][A-Z0-9.]{0,9}",sym)
                or row.get("side") not in ("BUY","SELL")):
            raise WebullReceiptUnverified("WEBULL_LEGACY_INVENTORY_IDENTITY_INVALID")
        qty=_money(row.get("filled_qty"),"WEBULL_LOCAL_FILLED_QUANTITY")
        if qty<=0 or qty!=qty.to_integral_value():
            raise WebullReceiptUnverified("WEBULL_LEGACY_INVENTORY_QUANTITY_INVALID")
        old=bot.get(sym,Decimal("0"))
        if row["side"]=="SELL" and qty>old:
            raise WebullReceiptUnverified("WEBULL_LEGACY_SELL_EXCEEDS_BOT_HOLDINGS")
        bot[sym]=old+(qty if row["side"]=="BUY" else -qty)
    if any(qty>signed.get(sym,Decimal("0")) for sym,qty in bot.items()):
        raise WebullReceiptUnverified("WEBULL_BOT_INVENTORY_EXCEEDS_SIGNED_HOLDINGS")
    return sum(1 for sym,qty in signed.items() if qty>bot.get(sym,Decimal("0")))


def probe_webull(root, broker, policy, *, now=None):
    now = now or datetime.now(timezone.utc)
    if not isinstance(now,datetime) or now.tzinfo is None:
        raise ValueError("Time must be timezone-aware")
    out = {
        "schema":1, "broker":"webull",
        "settlement_contract_version":1,
        "checked_at":now.astimezone(timezone.utc).isoformat(),
        "mode":"AUTHENTICATED_WEBULL_READ_ONLY",
        "live_order_authority":False, "cutover_ready":False,
        "broker_account_verified":False, "funding_verified":False,
        "settled_cash_verified":False, "broker_positions_verified":False,
        "broker_position_inventory_reconciled":False,
        "broker_open_orders_verified":False, "broker_open_order_count":None,
        "local_order_count":None, "local_unresolved_count":None,
        "signed_historical_fills_verified":False,
        "v1_writer_handoff_verified":False,
        "first_blocker":"OPERATOR_POLICY_UNVERIFIED",
        "live_v2_orders_submitted":0,
    }
    if not isinstance(policy,dict):
        out["first_blocker"]="WEBULL_OPERATOR_POLICY_UNVERIFIED"
        return out
    armed=policy.get("enabled") is True
    out["v1_operator_armed"]=armed
    # Running a signed GET-only preflight does not authorize trading. Permit
    # a configured but DISARMED account to be inspected before its cutover.
    choices = []
    for active, field in (("trade_stocks","stock_account"),("trade_crypto","crypto_account")):
        account_ref=policy.get(field)
        if isinstance(account_ref,str) and account_ref and (
                policy.get(active) is True or not armed):
            choices.append(account_ref)
    accounts = set(choices)
    if len(accounts)!=1:
        out["first_blocker"]="SELECT_ONE_WEBULL_ACCOUNT_FOR_MIGRATION"
        return out
    account = choices[0]
    try:
        details = broker.verify_account(account)
        if not isinstance(details,dict) or details.get("account_id") != account:
            raise ValueError("Selected account not signed")
        out["broker_account_verified"]=True
    except Exception:
        out["first_blocker"]="WEBULL_SIGNED_ACCOUNT_UNVERIFIED"
        return out
    try:
        balances = broker.balance(account)
        cash = _money(balances.get("total_cash_balance"),"WEBULL_CASH")
        equity = _money(balances.get("total_net_liquidation_value"),"WEBULL_EQUITY")
        market = _money(balances.get("total_market_value"),"WEBULL_MARKET_VALUE")
        if cash > equity or market > equity + Decimal("0.01"):
            raise WebullReceiptUnverified("WEBULL_BALANCE_CONTRADICTORY")
        out["funding_verified"]=True
        # No amounts or account identifiers are persisted in the migration
        # report. A missing optional settled-cash field remains unverified.
        verified_budget=signed_settled_cash_budget(balances)
        out["settled_cash_verified"]=(verified_budget is not None and verified_budget>0)
        out["funding_source"]=("SIGNED_VERIFIED_SETTLED_USD" if out["settled_cash_verified"]
            else "SIGNED_TOTAL_CASH_SETTLEMENT_NOT_VERIFIED")
    except Exception:
        out["first_blocker"]="WEBULL_SIGNED_CASH_OR_EQUITY_UNVERIFIED"
        return out
    try:
        positions = broker.positions(account)
        if not isinstance(positions,list):
            raise ValueError("Positions unavailable")
        # Broker position quantities and long/short are product-specific;
        # the new V2 adapter must normalize all positions before cutover.
        signed_positions=_signed_stock_positions(positions)
        out["broker_position_rows_observed"]=len(positions)
        out["broker_positions_verified"]=True
    except WebullReceiptUnverified as exc:
        out["first_blocker"]=exc.code
        return out
    except Exception:
        out["first_blocker"]="WEBULL_SIGNED_HOLDINGS_UNVERIFIED"
        return out
    try:
        open_orders = broker.open_orders(account)
        if not isinstance(open_orders,list) or any(not isinstance(x,dict) for x in open_orders):
            raise ValueError("Invalid broker open-order list")
        out["broker_open_orders_verified"]=True
        out["broker_open_order_count"]=len(open_orders)
        if open_orders:
            out["first_blocker"]="WEBULL_BROKER_OPEN_ORDERS_REQUIRE_RECONCILIATION"
            return out
    except Exception:
        out["first_blocker"]="WEBULL_OPEN_ORDER_HISTORY_UNVERIFIED"
        return out
    try:
        rows = _local_rows(root,account)
        out["local_order_count"]=len(rows)
        unresolved=[x for x in rows if x["status"] not in ("FILLED","CANCELLED","FAILED")]
        out["local_unresolved_count"]=len(unresolved)
        if unresolved:
            out["first_blocker"]="WEBULL_LOCAL_UNRESOLVED_ORDERS"
            return out
        # A single interactive preflight must never exhaust Webull's shared
        # per-app signed order-detail quota or hold the dashboard open for
        # hundreds of seconds. Mature journals require bounded pagination.
        if sum(row["status"]=="FILLED" for row in rows)>8:
            raise WebullReceiptUnverified("WEBULL_HISTORICAL_SIGNED_BATCH_REQUIRED")
        # This is signed detail verification of existing V1 fills, not a
        # conversion of historical V1 orders into new V2 order intents.
        matched=0
        for row in rows:
            if row["status"]!="FILLED":
                continue
            raw=broker.order_detail(account,row["client_id"])
            from webull_journal import WebullJournal
            signed=WebullJournal._detail(raw,row["client_id"])
            if (signed.get("status","").upper()!="FILLED"
                or signed.get("order_id")!=row["broker_id"]):
                raise WebullReceiptUnverified("WEBULL_HISTORICAL_BROKER_ID_MISMATCH")
            qty=_money(signed.get("filled_quantity"),"SIGNED_QUANTITY")
            price=_money(signed.get("filled_price"),"SIGNED_FILL_PRICE")
            fee=_money(signed.get("fee_charged"),"SIGNED_FILL_FEE")
            if (qty!=_money(row["filled_qty"],"LOCAL_QUANTITY")
                or price!=_money(row["filled_price"],"LOCAL_PRICE")
                or fee!=_money(row["fee"],"LOCAL_FEE")):
                raise WebullReceiptUnverified("WEBULL_HISTORICAL_FILL_ECONOMICS_MISMATCH")
            matched+=1
        out["signed_historical_fill_count"]=matched
        out["signed_historical_fills_verified"]=True
        out["broker_external_position_symbols"]=_legacy_bot_inventory(rows,signed_positions)
        out["broker_position_inventory_reconciled"]=True
    except WebullReceiptUnverified as exc:
        out["first_blocker"]=exc.code
        return out
    except Exception:
        out["first_blocker"]="WEBULL_HISTORICAL_ORDER_READ_UNVERIFIED"
        return out
    # V2 still requires precise position inventory, settled funding,
    # broker executable quote/session and the durable V1/V2 writer handoff.
    out["first_blocker"]=(
        "WEBULL_OPERATOR_NOT_ARMED" if not armed
        else "WEBULL_SESSION_AND_SINGLE_WRITER_HANDOFF_REQUIRED"
             if out["settled_cash_verified"]
        else "WEBULL_SETTLEMENT_AND_SINGLE_WRITER_HANDOFF_REQUIRED")
    return out
