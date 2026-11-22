"""Strict read-only adoption of legacy broker-verified V1 bot lots.

Never uses external holdings as bot inventory, never copies credentials,
writes V1 state or treats local journals alone as broker confirmation.
"""
from __future__ import annotations
from datetime import datetime,timezone
from decimal import Decimal
from pathlib import Path
import sqlite3,stat
from .models import Account,AuthState,amount,utc,valid_symbol
from .account_exit_rules import ManagedExitLot,ExitPolicy
from .v1_order_inheritance import read_inherited,V1InheritanceUnavailable

class V1LotUnavailable(ValueError):
    def __init__(self,code):
        self.code=code
        super().__init__(code)

def _positive(value,label):
    try:return amount(value,label,False)
    except (TypeError,ValueError):
        raise V1LotUnavailable("V1_MANAGED_LOT_"+label.upper()+"_INVALID") from None

def _timestamp(value):
    if not isinstance(value,str):raise V1LotUnavailable("V1_MANAGED_LOT_OPENED_AT_UNVERIFIED")
    try:
        stamp=datetime.fromisoformat(value.replace("Z","+00:00"))
        return utc(stamp)
    except (ValueError,TypeError,OverflowError):
        raise V1LotUnavailable("V1_MANAGED_LOT_OPENED_AT_UNVERIFIED") from None

def _webull_position(root,account,symbol):
    # Explicit read-only SQLite; never call the V1 constructor, which can
    # create tables or modify permissions when a journal is missing.
    path=root/"webull"/"orders.sqlite3"
    if path.is_symlink():raise V1LotUnavailable("V1_WEBULL_JOURNAL_SYMLINK")
    try:
        st=path.stat()
        if not stat.S_ISREG(st.st_mode) or st.st_mode&0o077 or st.st_size>30000000:
            raise ValueError("Unsupported file")
        with sqlite3.connect("file:"+str(path.absolute())+"?mode=ro",
                             uri=True,timeout=4) as db:
            db.execute("PRAGMA query_only=ON")
            rows=db.execute("""SELECT side,status,filled_qty,filled_price,fee,fill_at
               FROM orders WHERE account=? AND asset='EQUITY' AND symbol=?
               ORDER BY created_at,client_id LIMIT 20001""",
               (account,symbol)).fetchall()
        if len(rows)>20000:raise ValueError("Too many orders")
    except (sqlite3.Error,ValueError,OSError):
        raise V1LotUnavailable("V1_WEBULL_SIGNED_LOTS_UNAVAILABLE") from None
    qty=cost=Decimal("0")
    opened=None
    for side,status,raw_qty,raw_price,raw_fee,raw_at in rows:
        if status not in ("FILLED","CANCELLED","FAILED"):
            raise V1LotUnavailable("V1_WEBULL_BROKER_ORDER_NOT_FINAL")
        if status!="FILLED":continue
        q=_positive(raw_qty,"filled_quantity")
        price=_positive(raw_price,"fill_price")
        try:fee=amount(raw_fee,"verified signed fee")
        except (TypeError,ValueError):
            raise V1LotUnavailable("V1_WEBULL_BROKER_FEE_UNVERIFIED") from None
        filled_at=_timestamp(raw_at)
        if side=="BUY":
            if qty==0:opened=filled_at
            cost+=q*price+fee
            qty+=q
        elif side=="SELL":
            if q>qty:
                raise V1LotUnavailable("V1_WEBULL_SELL_EXCEEDS_VERIFIED_LOTS")
            average=cost/qty
            qty-=q
            cost-=q*average
            if qty==0:cost=Decimal("0");opened=None
        else:raise V1LotUnavailable("V1_WEBULL_ORDER_SIDE_UNVERIFIED")
    if qty<=0 or opened is None:
        raise V1LotUnavailable("V1_WEBULL_MANAGED_POSITION_UNAVAILABLE")
    return {"quantity":qty,"average_unit_cost":cost/qty,
            "opened_at":opened,"high_water_bid":None}

def managed_v1_lot(state_dir,broker,raw_account,symbol,account:Account,*,now=None):
    """Return typed proven V1 lot when exact signed brokerage inventory matches."""
    now=utc(now or datetime.now(timezone.utc))
    root=Path(state_dir)
    valid_symbol(symbol)
    if (not isinstance(account,Account) or account.broker!=broker or
        account.auth is not AuthState.CONNECTED or
        not isinstance(raw_account,str) or not raw_account or
        (broker in ("robinhood_crypto","webull") and
         account.account_id!=raw_account)):
        raise V1LotUnavailable("V1_MANAGED_SIGNED_ACCOUNT_UNVERIFIED")
    try:activity=read_inherited(root,broker,raw_account,now=now)
    except (V1InheritanceUnavailable,ValueError,OSError):
        raise V1LotUnavailable("V1_SIGNED_HISTORY_AND_ACCOUNT_REQUIRED") from None
    # The caller's Account contract must have been constructed by the signed
    # live broker adapter. Do not assume a local journal can prove quantity.
    actual=account.positions.get(symbol)
    if not isinstance(actual,Decimal) or actual<=0:
        raise V1LotUnavailable("V1_SIGNED_MANAGED_ASSET_ABSENT")
    if broker=="robinhood_crypto":
        try:
            from robinhood_order_journal import OrderJournal
            from robinhood_exit_tracker import ExitTracker
            journal=OrderJournal(root)
            # The V1 cost-basis projection treats an absent historical
            # broker fee as zero for its own diagnostics. V2 cannot inherit
            # that assumption when certifying a live managed lot.
            history=journal.load()
            for receipt in history.get("orders",[]):
                if not isinstance(receipt,dict):
                    raise ValueError("Historical order record malformed")
                if (receipt.get("account")==raw_account and
                    receipt.get("symbol")==symbol and
                    receipt.get("status")=="filled" and
                    receipt.get("side") in ("buy","sell")):
                    if (receipt.get("fee_charged") is None or
                        receipt.get("fee_verified") is False):
                        raise ValueError("Original signed fill fee not verified")
            records=journal.positions(raw_account)
            row=records.get(symbol)
            if not isinstance(row,dict) or row.get("cost_basis_verified") is not True:
                raise ValueError
            signed_qty=_positive(row.get("quantity"),"quantity")
            cost=_positive(row.get("average_unit_cost"),"cost")
            opened=_timestamp(row.get("opened_at"))
            peak=ExitTracker(root).peak(raw_account,symbol,row)
        except Exception:
            raise V1LotUnavailable("V1_ROBINHOOD_BROKER_CONFIRMED_LOT_UNVERIFIED") from None
    elif broker=="webull":
        info=_webull_position(root,raw_account,symbol)
        signed_qty=info["quantity"];cost=info["average_unit_cost"]
        opened=info["opened_at"];peak=None
    elif broker=="schwab":
        # Existing Schwab V1 ledger tracks shares + execution legs, but
        # historical broker-confirmed cumulative cost/fee provenance is not
        # consistently maintained, especially the manually adopted SPYD lot.
        # Do not silently price or adopt that holding from a market quote.
        raise V1LotUnavailable("V1_SCHWAB_SIGNED_MANAGED_COST_BASIS_REQUIRED")
    else:
        raise V1LotUnavailable("V1_MANAGED_BROKER_UNSUPPORTED")
    if (signed_qty!=actual or opened>now or
        not activity.local_journal_terminal or
        not activity.signed_broker_history_fresh):
        raise V1LotUnavailable("V1_BOT_LOT_OR_SIGNED_AVAILABILITY_MISMATCH")
    return ManagedExitLot(symbol,signed_qty,actual,cost,opened,
        high_water_bid=peak,cost_basis_broker_verified=True,
        original_fills_reconciled=True,
        same_day_filled_buy=(
             opened.date()==now.date() if broker=="robinhood_crypto" else
             opened.astimezone(__import__("zoneinfo").ZoneInfo(
                 "America/New_York")).date()==now.astimezone(
                 __import__("zoneinfo").ZoneInfo("America/New_York")).date()))

def legacy_exit_policy(state_dir,broker,raw_account):
    """Reconstruct the saved legacy exit settings, not a global default."""
    root=Path(state_dir)
    if broker=="webull":return ExitPolicy("webull")
    if broker=="schwab":return ExitPolicy("schwab")
    if broker!="robinhood_crypto":
        raise V1LotUnavailable("V1_BROKER_EXIT_POLICY_UNSUPPORTED")
    try:
        from robinhood_policy import read_policy
        from robinhood_order_journal import OrderJournal
        from robinhood_fee_estimates import effective_sell_fee_pct
        policy=read_policy(root)
        if policy.get("account")!=raw_account:
            raise ValueError("Selected account mismatch")
        fee,source=effective_sell_fee_pct(policy,OrderJournal(root))
        params={name:Decimal(str(policy[key])) for name,key in (
         ("stop_loss_pct","stop_loss_pct"),
         ("min_profit_pct","min_profit_pct"),
         ("take_profit_pct","take_profit_pct"),
         ("trailing_activation_pct","trailing_activation_pct"),
         ("trailing_drawdown_pct","trailing_drawdown_pct"))}
        return ExitPolicy("robinhood_crypto",
           **params,min_hold_minutes=int(policy["min_hold_minutes"]),
           sell_fee_pct=fee,
           stop_reference_fee_pct=Decimal(str(policy["fee_buffer_pct"])))
    except Exception:
        raise V1LotUnavailable("V1_ROBINHOOD_SAVED_EXIT_POLICY_UNVERIFIED") from None
