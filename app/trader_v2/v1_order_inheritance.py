"""Read-only V1 account order-count and cooldown inheritance for V2.

Never lets a V2 cutover reset V1 daily entry/exit counts or buy cooldowns.
Every local journal requires an independently signed recent GET preflight,
correct selected account and no unresolved V1 or broker orders. This module
does not create permissions or read broker credentials or submit orders.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime,timezone,timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo
import sqlite3,stat
from .models import utc,valid_symbol
from .readonly_adapters import private_json
from .launch_gates import launch_status

_ET=ZoneInfo("America/New_York")
_TERMINAL_RH=frozenset({"filled","canceled","cancelled","failed",
                        "rejected","expired","externally_reconciled"})
_TERMINAL_WB=frozenset({"FILLED","CANCELLED","FAILED"})

class V1InheritanceUnavailable(ValueError):
    def __init__(self,code):
        self.code=code
        super().__init__(code)

@dataclass(frozen=True)
class InheritedOrderLimits:
    broker:str
    account:str
    entries_today:int
    exits_today:int
    reentry_blocked_symbols:frozenset[str]
    all_buys_blocked:bool
    signed_broker_history_fresh:bool
    local_journal_terminal:bool
    max_daily_total_orders:int|None=None
    def __post_init__(self):
        if (self.broker not in ("schwab","webull","robinhood_crypto") or
                not isinstance(self.account,str) or not self.account or
                type(self.entries_today) is not int or
                type(self.exits_today) is not int or
                min(self.entries_today,self.exits_today)<0 or
                (self.max_daily_total_orders is not None and
                 (type(self.max_daily_total_orders) is not int or
                  not 1<=self.max_daily_total_orders<=100)) or
                type(self.all_buys_blocked) is not bool or
                self.signed_broker_history_fresh is not True or
                self.local_journal_terminal is not True or
                not isinstance(self.reentry_blocked_symbols,frozenset) or
                any(not isinstance(s,str) for s in self.reentry_blocked_symbols)):
            raise V1InheritanceUnavailable("V1_INHERITED_COUNTS_INVALID")

def _stamp(raw,now):
    if not isinstance(raw,str):
        raise V1InheritanceUnavailable("V1_ORDER_TIMESTAMP_MISSING")
    try:dt=utc(datetime.fromisoformat(raw.replace("Z","+00:00")))
    except (ValueError,TypeError,OverflowError):
        raise V1InheritanceUnavailable("V1_ORDER_TIMESTAMP_INVALID") from None
    if (dt-now).total_seconds()>5:
        raise V1InheritanceUnavailable("V1_ORDER_TIMESTAMP_FUTURE")
    return dt

def _date(moment,broker):
    return moment.astimezone(_ET if broker!="robinhood_crypto" else timezone.utc).date()

def inherit_records(broker,account,records,*,now,policy=None):
    """Pure per-account V1 journal projection, requires signed caller evidence.

    This helper never claims broker history matched; the production reader
    independently verifies that in fresh signed migration gate evidence.
    """
    now=utc(now)
    if (broker not in ("schwab","webull","robinhood_crypto") or
        not isinstance(account,str) or not account or
        not isinstance(records,list) or len(records)>20000 or
        any(not isinstance(x,dict) for x in records)):
        raise V1InheritanceUnavailable("V1_ORDER_RECORDS_INVALID")
    entries=exits=0
    seen=set()
    last_sell=None
    today=_date(now,broker)
    for row in records:
        owner=row.get("account")
        if owner is not None and owner!=account:
            if broker=="schwab":
                raise V1InheritanceUnavailable("SCHWAB_ACCOUNT_RECORD_MISMATCH")
            continue
        identity=(row.get("client_id") if broker=="webull" else
                  row.get("client_order_id") if broker=="robinhood_crypto" else
                  row.get("order_id"))
        # Schwab unsubmitted canceled records may have no broker ID. Its
        # settled-journal evidence already requires signed ID matching.
        if broker=="robinhood_crypto" and row.get("side")=="external_reduction":
            ids=row.get("external_broker_order_ids")
            if (not isinstance(ids,list) or not ids or
                any(not isinstance(x,str) or not x for x in ids) or
                len(set(ids))!=len(ids)):
                raise V1InheritanceUnavailable("V1_EXTERNAL_BROKER_IDS_UNVERIFIED")
            identity=("EXTERNAL_SIGNED",tuple(sorted(ids)))
        if identity is None and broker=="schwab":
            identity=("LOCAL",row.get("created_at"),row.get("symbol"),
                      row.get("action"))
        if identity is None or identity in seen:
            raise V1InheritanceUnavailable("V1_ORDER_IDENTITY_INVALID_OR_DUPLICATE")
        seen.add(identity)
        status=(row.get("status") if broker!="schwab" else row.get("state"))
        allowed=(_TERMINAL_RH if broker=="robinhood_crypto" else
                 _TERMINAL_WB if broker=="webull" else
                 frozenset({"FILLED","CANCELED","REJECTED","EXPIRED","REPLACED"}))
        if status not in allowed:
            raise V1InheritanceUnavailable("V1_ORDER_NOT_TERMINAL")
        entered=_stamp(row.get("created_at"),now)
        side=row.get("action") if broker=="schwab" else row.get("side")
        if broker=="robinhood_crypto":
            if side=="external_reduction":
                if status!="externally_reconciled":
                    raise V1InheritanceUnavailable("V1_EXTERNAL_REDUCTION_UNVERIFIED")
                side="SELL"
            elif side in ("buy","sell"):side=side.upper()
        if side not in ("BUY","SELL"):
            raise V1InheritanceUnavailable("V1_ORDER_SIDE_UNVERIFIED")
        if _date(entered,broker)==today:
            if side=="BUY":entries+=1
            else:exits+=1
        if side=="SELL" and status in ("FILLED","filled","externally_reconciled"):
            when=_stamp(row.get("fill_at") if broker=="webull" else
                row.get("filled_at") if broker=="robinhood_crypto" else
                row.get("created_at"),now)
            symbol=row.get("symbol")
            if not isinstance(symbol,str):
                raise V1InheritanceUnavailable("V1_EXIT_SYMBOL_UNVERIFIED")
            valid_symbol(symbol)
            if last_sell is None or when>last_sell[0]:last_sell=(when,symbol)
    total_cap=None
    if broker=="schwab":
        if not isinstance(policy,dict) or type(policy.get("max_orders_per_day")) is not int:
            raise V1InheritanceUnavailable("V1_SCHWAB_DAILY_TOTAL_ORDER_LIMIT_UNVERIFIED")
        total_cap=policy["max_orders_per_day"]
        if not 1<=total_cap<=100:
            raise V1InheritanceUnavailable("V1_SCHWAB_DAILY_TOTAL_ORDER_LIMIT_INVALID")
    blocked=set()
    all_buys=False
    if broker=="schwab" and last_sell is not None:
        next_day=_date(last_sell[0],broker)+timedelta(days=1)
        while next_day.weekday()>4:next_day+=timedelta(days=1)
        all_buys=today<next_day
    if broker=="robinhood_crypto":
        if not isinstance(policy,dict) or type(policy.get("reentry_cooldown_minutes")) is not int:
            raise V1InheritanceUnavailable("V1_REENTRY_COOLDOWN_POLICY_UNVERIFIED")
        wait=policy["reentry_cooldown_minutes"]
        if not 0<=wait<=1440:
            raise V1InheritanceUnavailable("V1_REENTRY_COOLDOWN_POLICY_INVALID")
        # Every recent signed bot sell/external reduction blocks matching
        # reentry, not merely the last symbol sold in the account.
        for row in records:
            if row.get("account")!=account or row.get("side") not in (
                    "sell","external_reduction"):
                continue
            if row.get("status") not in ("filled","externally_reconciled"):continue
            when=_stamp(row.get("filled_at"),now)
            delta=(now-when).total_seconds()/60
            if -0.05<=delta<wait:
                sym=row.get("symbol")
                valid_symbol(sym)
                blocked.add(sym)
    return InheritedOrderLimits(broker,account,entries,exits,
                               frozenset(blocked),all_buys,True,True,total_cap)

def _read_webull(root,account):
    path=root/"webull/orders.sqlite3"
    if path.is_symlink():raise V1InheritanceUnavailable("V1_JOURNAL_SYMLINK")
    try:
        st=path.stat()
        if not stat.S_ISREG(st.st_mode) or st.st_mode&0o077 or st.st_size>30_000_000:
            raise ValueError
        with sqlite3.connect("file:"+str(path.absolute())+"?mode=ro",uri=True,timeout=3) as db:
            db.execute("PRAGMA query_only=ON")
            rows=db.execute("SELECT account,client_id,side,status,created_at,fill_at,symbol "
                "FROM orders WHERE account=? ORDER BY created_at LIMIT 20001",
                (account,)).fetchall()
        if len(rows)>20000:raise ValueError
    except (OSError,ValueError,sqlite3.Error):
        raise V1InheritanceUnavailable("V1_WEBULL_JOURNAL_UNVERIFIED") from None
    names=("account","client_id","side","status","created_at","fill_at","symbol")
    return [dict(zip(names,row)) for row in rows]

def read_inherited(state_dir,broker,account,*,now=None,policy=None):
    """Produce inherited counts only after all fresh signed history gates pass."""
    now=utc(now or datetime.now(timezone.utc))
    root=Path(state_dir)
    launch=launch_status(root,broker,now=now)
    verified={x["name"] for x in launch["gates"] if x["verified"] is True}
    required={"SIGNED_PREFLIGHT_FRESH","SIGNED_ACCOUNT","SIGNED_HOLDINGS",
              "SIGNED_ORDER_HISTORY","NO_OPEN_OR_UNRESOLVED_ORDERS"}
    if not required.issubset(verified):
        raise V1InheritanceUnavailable("V1_SIGNED_ACCOUNT_HISTORY_NOT_FRESH")
    if broker=="webull":
        from webull_trade_config import read
        cfg=read(root)
        if (cfg.get("stock_account")!=account or cfg.get("trade_stocks") is not True):
            raise V1InheritanceUnavailable("V1_WEBULL_SELECTED_ACCOUNT_MISMATCH")
        rows=_read_webull(root,account)
    elif broker=="robinhood_crypto":
        saved=private_json(root/"robinhood/risk_policy.json",maximum=16000)
        if not isinstance(saved,dict) or saved.get("account")!=account:
            raise V1InheritanceUnavailable("V1_ROBINHOOD_SELECTED_ACCOUNT_MISMATCH")
        if policy is None:policy=saved
        doc=private_json(root/"robinhood/order_intents.json",maximum=4000000)
        if not isinstance(doc,dict) or doc.get("version")!=1:
            raise V1InheritanceUnavailable("V1_ROBINHOOD_JOURNAL_UNVERIFIED")
        rows=doc.get("orders")
    else:
        from unified_config import settings
        cfg=settings(root)
        if cfg.get("live_account_hash")!=account:
            raise V1InheritanceUnavailable("V1_SCHWAB_SELECTED_ACCOUNT_MISMATCH")
        risk=private_json(root/"live/risk_settings.json",maximum=16000)
        if (not isinstance(risk,dict) or risk.get("version")!=1 or
            not isinstance(risk.get("settings"),dict)):
            raise V1InheritanceUnavailable("V1_SCHWAB_DAILY_RISK_SETTINGS_UNVERIFIED")
        policy=risk["settings"]
        doc=private_json(root/"live/orders.json",maximum=4000000)
        if not isinstance(doc,dict) or doc.get("version")!=1 or doc.get("halted") is not False:
            raise V1InheritanceUnavailable("V1_SCHWAB_JOURNAL_UNVERIFIED")
        rows=doc.get("orders")
    return inherit_records(broker,account,rows,now=now,policy=policy)
