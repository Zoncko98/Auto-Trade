"""V2 Phase 2: source-specific READ-ONLY account adapters over V1 broker observations.

No broker client imports, no network access, no orders, no credential reads.
Worker files are authoritative ONLY if fresh, private, and consistent with
the selected account and user-owned V1 policy. Never infer cash from buying power.
"""
from __future__ import annotations
from dataclasses import dataclass,asdict
from datetime import datetime,timezone
from decimal import Decimal
from pathlib import Path
from typing import Mapping
import json,os,stat
from .models import AssetClass,AuthState,amount

MAX_AGE=180
MAX_SIZE=1_500_000
_NAMES=("schwab","webull","robinhood_crypto","paper")

def private_json(path,*,maximum=MAX_SIZE):
    """Read bounded private JSON without following symlinks, never create state."""
    path=Path(path)
    flags=os.O_RDONLY | getattr(os,"O_NOFOLLOW",0) | getattr(os,"O_CLOEXEC",0)
    try:
        fd=os.open(path,flags)
        try:
            st=os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_mode & 0o077 or not 1<=st.st_size<=maximum:
                return None
            with os.fdopen(fd,"r",encoding="utf-8") as stream:
                fd=None
                raw=stream.read(maximum+1)
            if len(raw)>maximum:return None
            obj=json.loads(raw)
            return obj if isinstance(obj,dict) else None
        finally:
            if fd is not None:os.close(fd)
    except (OSError,ValueError,TypeError,UnicodeError):
        return None

def time_seen(value,now):
    if not isinstance(value,str) or len(value)>45:return None
    try:
        at=datetime.fromisoformat(value.replace("Z","+00:00"))
        if at.tzinfo is None:return None
        at=at.astimezone(timezone.utc)
        age=(now-at).total_seconds()
        return at if -5<=age<=MAX_AGE else None
    except (ValueError,OverflowError,TypeError):return None

def money(value):
    if value is None or type(value) is bool:return None
    try:return amount(str(value),"broker value")
    except (ValueError,TypeError):return None

@dataclass(frozen=True)
class AccountObservation:
    broker:str
    asset_class:AssetClass
    auth:AuthState
    worker_state:str
    permission_armed:bool
    read_verified:bool
    observed_at:datetime|None
    reason_code:str
    source:str
    cash_usd:Decimal|None=None
    equity_usd:Decimal|None=None
    buying_power_usd:Decimal|None=None
    exposure_usd:Decimal|None=None
    entry_headroom_usd:Decimal|None=None
    account_class:str="UNVERIFIED"
    def __post_init__(self):
        if self.broker not in _NAMES or self.worker_state not in (
            "ONLINE","OFFLINE","DEGRADED","PAPER_ONLY"):
            raise ValueError("Unknown V2 broker identity or worker state")
        if not isinstance(self.asset_class,AssetClass) or not isinstance(self.auth,AuthState):
            raise ValueError("Invalid V2 account classification")
        if not isinstance(self.permission_armed,bool) or not isinstance(self.read_verified,bool):
            raise ValueError("Invalid account flags")
        if not isinstance(self.reason_code,str) or len(self.reason_code)>90:
            raise ValueError("Invalid status reason")
        for key in ("cash_usd","equity_usd","buying_power_usd",
                    "exposure_usd","entry_headroom_usd"):
            value=getattr(self,key)
            if value is not None and (not isinstance(value,Decimal) or value<0):
                raise ValueError("Noncanonical account valuation")
        if self.observed_at is not None and self.observed_at.tzinfo is None:
            raise ValueError("Account observation must be timezone-aware")
        if not self.read_verified:
            if any(getattr(self,key) is not None for key in
                ("cash_usd","equity_usd","buying_power_usd","exposure_usd","entry_headroom_usd")):
                raise ValueError("Unverified account cannot assert current financial values")
    def public(self):
        doc=asdict(self)
        doc["asset_class"]=self.asset_class.value
        doc["auth"]=self.auth.value
        doc["observed_at"]=self.observed_at.isoformat() if self.observed_at else None
        for key in ("cash_usd","equity_usd","buying_power_usd",
                    "exposure_usd","entry_headroom_usd"):
            value=getattr(self,key)
            doc[key]=str(value) if value is not None else None
        return doc

def unavailable(broker,reason,*,armed=False,state="OFFLINE"):
    asset=AssetClass.CRYPTO if broker=="robinhood_crypto" else AssetClass.STOCK
    return AccountObservation(broker,asset,AuthState.TEMPORARY_ERROR,state,
          armed,False,None,reason,"UNVERIFIED")

def _schwab(root,now):
    root=Path(root)
    hb=private_json(root/"live/worker_heartbeat.json",maximum=20000)
    snapshot=private_json(root/"live/account_snapshot.json")
    supervisor=private_json(root/"live/supervisor_status.json",maximum=20000) or {}
    operator=private_json(root/"live/operator.json",maximum=10000) or {}
    mode=operator.get("mode")
    armed=mode=="running"
    at=time_seen(hb.get("at"),now) if hb else None
    if at and (now-at).total_seconds()>120:
        at=None  # V1 live_state considers >120s offline; V2 must agree.
    if not at:
        if str(supervisor.get("reason","")).upper() in ("INVALID_GRANT","REAUTH_REQUIRED"):
            return AccountObservation("schwab",AssetClass.STOCK,AuthState.REAUTH_REQUIRED,
                "OFFLINE",armed,False,None,"BROKER_OAUTH_REAUTH_REQUIRED","SCHWAB_SUPERVISOR")
        state="MANUAL_REVIEW_REQUIRED" if supervisor.get("state")=="MANUAL_REVIEW_REQUIRED" else "WORKER_HEARTBEAT_STALE"
        return unavailable("schwab",state,armed=armed)
    snap_at=time_seen(snapshot.get("at"),now) if snapshot else None
    if not snap_at or snap_at>at:
        return unavailable("schwab","ACCOUNT_SNAPSHOT_STALE_OR_MISSING",armed=armed,state="DEGRADED")
    cash=money(snapshot.get("cash"))
    equity=money(snapshot.get("equity"))
    exposure=money(snapshot.get("exposure"))
    if cash is None or equity is None or exposure is None or cash>equity+Decimal("0.01"):
        return unavailable("schwab","ACCOUNT_VALUE_UNVERIFIED",armed=armed,state="DEGRADED")
    return AccountObservation("schwab",AssetClass.STOCK,AuthState.CONNECTED,
        "ONLINE",armed,True,snap_at,"AUTHENTICATED_WORKER_SNAPSHOT",
        "SCHWAB_LIVE_WORKER",cash_usd=cash,equity_usd=equity,
        exposure_usd=exposure,account_class="CASH")

def _webull(root,now):
    root=Path(root)
    report=private_json(root/"webull/worker_status.json")
    policy=private_json(root/"webull/trading_policy.json",maximum=30000)
    cred_file=root/"config/webull_openapi.json"
    armed=policy.get("enabled") is True if policy else False
    if not report or not policy:
        return unavailable("webull","WORKER_OR_POLICY_UNAVAILABLE",armed=armed)
    at=time_seen(report.get("updated_at"),now)
    if not at or report.get("worker")!="RUNNING":
        return unavailable("webull","WORKER_HEARTBEAT_STALE",armed=armed)
    # Never accept a previously signed worker result after credentials rotated.
    try:
        st=cred_file.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_mode&0o077 or st.st_mtime_ns>(
              root/"webull/worker_status.json").stat().st_mtime_ns:
            raise ValueError
    except (OSError,ValueError):
        return unavailable("webull","CREDENTIAL_ROTATED_OR_UNVERIFIED",armed=armed,state="DEGRADED")
    if report.get("environment")!="production" or policy.get("trade_stocks") is not True:
        return unavailable("webull","STOCK_ACCOUNT_NOT_SELECTED",armed=armed,state="DEGRADED")
    selected=policy.get("stock_account")
    broker_accounts=report.get("broker_accounts")
    sums=report.get("account_summaries")
    if not isinstance(selected,str) or not selected or not isinstance(broker_accounts,list) or not isinstance(sums,list):
        return unavailable("webull","BROKER_ACCOUNTS_UNVERIFIED",armed=armed,state="DEGRADED")
    accounts=[x for x in broker_accounts if isinstance(x,dict) and x.get("account_id")==selected]
    summaries=[x for x in sums if isinstance(x,dict) and x.get("account_id")==selected]
    if len(accounts)!=1 or len(summaries)!=1:
        return unavailable("webull","SELECTED_ACCOUNT_MISSING",armed=armed,state="DEGRADED")
    match=summaries[0]
    if match.get("environment")!="production" or match.get("currency")!="USD":
        return unavailable("webull","BROKER_USD_BALANCE_UNVERIFIED",armed=armed,state="DEGRADED")
    cash=money(match.get("cash"));equity=money(match.get("account_value"))
    exposure=money(match.get("market_value"))
    if cash is None or equity is None or exposure is None or cash>equity+Decimal("0.01"):
        return unavailable("webull","BROKER_USD_BALANCE_UNVERIFIED",armed=armed,state="DEGRADED")
    budget=report.get("stock_buy_readiness")
    headroom=money(budget.get("max_new_stock_usd")) if isinstance(budget,dict) else None
    kind=str(accounts[0].get("account_type") or "UNVERIFIED").upper()[:30]
    return AccountObservation("webull",AssetClass.STOCK,AuthState.CONNECTED,"ONLINE",
        armed,True,at,"AUTHENTICATED_WORKER_ACCOUNT_AND_BALANCE",
        "WEBULL_OPENAPI_WORKER",cash_usd=cash,equity_usd=equity,
        exposure_usd=exposure,entry_headroom_usd=headroom,account_class=kind)

def _robinhood(root,now):
    root=Path(root)
    report=private_json(root/"robinhood/worker_status.json")
    policy=private_json(root/"robinhood/risk_policy.json",maximum=40000)
    armed=(policy.get("enabled") is True and isinstance(policy.get("account"),str)
           and bool(policy.get("account"))) if policy else False
    if not report:return unavailable("robinhood_crypto","WORKER_UNAVAILABLE",armed=armed)
    at=time_seen(report.get("updated_at"),now)
    if not at or report.get("worker") not in ("monitoring","monitoring_degraded"):
        return unavailable("robinhood_crypto","WORKER_HEARTBEAT_STALE",armed=armed)
    accounts=report.get("accounts")
    if not isinstance(accounts,list) or not accounts:
        return unavailable("robinhood_crypto","BROKER_ACCOUNT_LIST_UNVERIFIED",armed=armed,state="DEGRADED")
    verified=[x for x in accounts if isinstance(x,dict) and x.get("api_tradable") is True
               and x.get("currency")=="USD" and money(x.get("buying_power_usd")) is not None]
    if len(verified)!=1:
        return unavailable("robinhood_crypto","USD_ACCOUNT_OR_BUYING_POWER_UNVERIFIED",
            armed=armed,state="DEGRADED")
    if report.get("worker")=="monitoring_degraded" or report.get("broker_order_history_status")!="VERIFIED":
        # A signed account observation is still read-only evidence of access,
        # but an unverified order journal cannot be mistaken for readiness.
        return AccountObservation("robinhood_crypto",AssetClass.CRYPTO,
             AuthState.CONNECTED,"DEGRADED",armed,True,at,
             "BROKER_ORDER_HISTORY_RECONCILIATION_REQUIRED","ROBINHOOD_SIGNED_WORKER",
             buying_power_usd=money(verified[0]["buying_power_usd"]),account_class="CRYPTO")
    return AccountObservation("robinhood_crypto",AssetClass.CRYPTO,
         AuthState.CONNECTED,"ONLINE",armed,True,at,
         "AUTHENTICATED_WORKER_CRYPTO_ACCOUNT","ROBINHOOD_SIGNED_WORKER",
         buying_power_usd=money(verified[0]["buying_power_usd"]),account_class="SPOT_CRYPTO")

def _paper(root,now):
    doc=private_json(Path(root)/"paper_account.json")
    if not doc or doc.get("schema")!=1:
        return unavailable("paper","PAPER_ACCOUNT_UNAVAILABLE")
    cash=money(doc.get("cash"))
    if cash is None:return unavailable("paper","PAPER_ACCOUNT_INVALID")
    # Virtual equity is NOT known without verified marks on all positions.
    positions=doc.get("positions",{})
    equity=cash if isinstance(positions,dict) and not positions else None
    return AccountObservation("paper",AssetClass.STOCK,AuthState.CONNECTED,
       "PAPER_ONLY",False,True,None,"LOCAL_SIMULATED_BALANCE","V1_PAPER_ACCOUNT",
       cash_usd=cash,equity_usd=equity,account_class="SIMULATED")

class ReadOnlyBrokerRegistry:
    """One normalized, strictly read-only view; never mutates financial state."""
    def __init__(self,state_dir):self.root=Path(state_dir)
    def inspect(self,broker,*,now=None):
        if broker not in _NAMES:raise ValueError("Unsupported broker")
        now=now or datetime.now(timezone.utc)
        if now.tzinfo is None:raise ValueError("Now must be timezone-aware")
        return {"schwab":_schwab,"webull":_webull,
                "robinhood_crypto":_robinhood,"paper":_paper}[broker](
                   self.root,now.astimezone(timezone.utc))
    def inspect_all(self,*,now=None):
        return [self.inspect(name,now=now) for name in _NAMES]
