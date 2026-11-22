"""Actual, signed Robinhood V2 service: never an automatic account cutover.

This module is loaded only by an explicitly enabled V2 executor. Its signed
order adapter is constructed only AFTER durable V2 ownership, a stopped V1
writer and a short-lived authenticated broker handoff are independently
verified. Failure at ANY boundary blocks the scan; no test-only booleans,
synthetic quotes, paper cash or external holdings can arm this service.
"""
from __future__ import annotations
from datetime import datetime,timezone,timedelta
from decimal import Decimal
from pathlib import Path
import sqlite3,stat

from .models import AssetClass,Candle,utc,amount
from .live_pipeline import WriterHandoff
from .writer_ownership import inspect_ownership
from .launch_gates import launch_status
from .readonly_adapters import private_json
from .v1_order_inheritance import read_inherited
from .live_position_projection import reconstruct
from .account_exit_rules import ManagedExitLot
from .v1_managed_lots import managed_v1_lot,legacy_exit_policy

_SUPPORTED={"BTC-USD":"BTCUSD","ETH-USD":"ETHUSD"}
_PROOF_TTL=75

def closed_crypto_bars(state_dir,symbol,*,now=None):
    """Read V2 public observed one-minute closes; no database creation/writes."""
    if symbol not in _SUPPORTED:raise ValueError("LIVE_PUBLIC_CANDLE_SYMBOL_UNSUPPORTED")
    now=utc(now or datetime.now(timezone.utc))
    path=Path(state_dir)/"v2/fresh_paper/tick_bars.sqlite3"
    if path.is_symlink():raise ValueError("LIVE_CANDLES_SYMLINK")
    info=path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode&0o077 or info.st_size>30000000:
        raise ValueError("LIVE_CANDLES_PRIVATE_DB_UNVERIFIED")
    current_minute=int(now.timestamp())//60*60
    with sqlite3.connect("file:"+str(path.absolute())+"?mode=ro",
                         uri=True,timeout=4) as db:
        db.execute("PRAGMA query_only=ON")
        rows=db.execute("""SELECT minute_start,close FROM tick_bars
          WHERE symbol=? AND minute_start<? ORDER BY minute_start DESC LIMIT 240""",
          (_SUPPORTED[symbol],current_minute)).fetchall()
    bars=[]
    for raw_stamp,raw_close in reversed(rows):
        stamp=datetime.fromtimestamp(raw_stamp+60,timezone.utc)
        bars.append(Candle(symbol,stamp,amount(raw_close,"public market close",False),True))
    return bars

def v1_inventory(root,account):
    from robinhood_order_journal import OrderJournal
    journal=OrderJournal(root)
    result={}
    records=journal.positions(account)
    if not isinstance(records,dict):raise ValueError("V1_MANAGED_INVENTORY_UNVERIFIED")
    for symbol,item in records.items():
        if not isinstance(item,dict) or item.get("cost_basis_verified") is not True:
            raise ValueError("V1_MANAGED_COST_BASIS_UNVERIFIED")
        qty=amount(item.get("quantity"),"V1 bot quantity",False)
        if qty>0:result[symbol]=qty
    return result

def v2_inventory(root,account):
    view=reconstruct(root,account)
    if view.get("state")!="RECONCILED" or view.get("unresolved_intents")!=0:
        raise ValueError("V2_ORDER_RECEIPTS_UNRESOLVED")
    rows=view.get("verified_v2_inventory")
    if not isinstance(rows,dict):raise ValueError("V2_INVENTORY_UNVERIFIED")
    result={}
    for symbol,item in rows.items():
        if (not isinstance(item,dict) or item.get("asset_class")!="CRYPTO"
                or symbol not in _SUPPORTED):
            raise ValueError("V2_CRYPTO_MANAGED_ASSET_UNSUPPORTED")
        result[symbol]=amount(item.get("quantity"),"V2 bot quantity",False)
    return result,view

def merged_bot_inventory(root,account):
    older=v1_inventory(root,account)
    current,view=v2_inventory(root,account)
    if any(sym in older and current.get(sym,Decimal("0"))>0 for sym in older):
        # Cost and holding periods of mixed generations must not be guessed.
        raise ValueError("MIXED_V1_V2_MANAGED_LOT_REQUIRES_INDEPENDENT_RECONCILIATION")
    return {**older,**current},view

def signed_v1_worker_stopped():
    """Actual same-container process observation, not a stale UI heartbeat."""
    base=Path("/proc")
    if not base.is_dir():return False
    observed=0
    for proc in base.iterdir():
        if not proc.name.isdigit():continue
        try:
            data=(proc/"cmdline").read_bytes()[:2048].split(b"\x00")
        except (OSError,PermissionError):
            continue
        observed+=1
        if any(arg.endswith(b"/robinhood_worker.py") for arg in data):
            return False
    return observed>0

def signed_robinhood_grant(root,broker,account):
    if broker!="robinhood_crypto":return None
    root=Path(root)
    from robinhood_policy import read_policy
    policy=read_policy(root)
    if policy.get("enabled") is not True or policy.get("account")!=account:
        return None
    owner=inspect_ownership(root,broker,account)
    if owner.get("owner")!="V2" or not isinstance(owner.get("generation"),str):
        return None
    if not signed_v1_worker_stopped():return None
    # Revalidate provider records while V2 owns the original account.
    # Rate of signed GET probes is bounded by the caller's once-per-cycle
    # invocation and cached reports; no POST is possible in this function.
    saved=private_json(root/"v2/broker_migration/robinhood_crypto.json",maximum=16000)
    now=datetime.now(timezone.utc)
    try:
        checked=utc(datetime.fromisoformat(saved["checked_at"]))
        fresh=-2<=(now-checked).total_seconds()<=_PROOF_TTL
    except Exception:fresh=False
    if not fresh:
        from .migration_probe import run_once
        saved=run_once(root)
    gates=launch_status(root,broker,now=now)
    needed=("SIGNED_PREFLIGHT_FRESH","SIGNED_ACCOUNT","SIGNED_HOLDINGS",
            "SIGNED_ORDER_HISTORY","NO_OPEN_OR_UNRESOLVED_ORDERS",
            "BROKER_PRODUCT_PERMISSIONS","EXECUTABLE_BROKER_QUOTE",
            "V1_SAVED_NUMERIC_RISK","SIGNED_SETTLED_FUNDING",
            "SIGNED_MARKET_SESSION")
    passed={g["name"] for g in gates["gates"] if g.get("verified") is True}
    if not set(needed).issubset(passed):return None
    inherited=read_inherited(root,broker,account,now=now)
    if not inherited.signed_broker_history_fresh or not inherited.local_journal_terminal:
        return None
    if not signed_v1_worker_stopped():return None
    again=inspect_ownership(root,broker,account)
    if again!=owner:return None
    return WriterHandoff(broker,account,owner["generation"],now,
       now+timedelta(seconds=40),True,True,True,True,True,True,True)

def verified_robinhood_parity(root,broker,account):
    if broker!="robinhood_crypto":return False
    root=Path(root)
    try:
        from robinhood_policy import read_policy
        policy=read_policy(root)
        if policy.get("enabled") is not True or policy.get("account")!=account:
            return False
        exit_rules=legacy_exit_policy(root,broker,account)
        if exit_rules.broker!=broker:return False
        inherited=read_inherited(root,broker,account)
        if not inherited.signed_broker_history_fresh or not inherited.local_journal_terminal:
            return False
        # Every open legacy bot lot must be safe to adopt via signed holding
        # verification when the canonical scan is assembled. Here policy
        # and inventory structure are validated before any writer is created.
        # A baseline V1 lot cannot be sold through a V2-only fill ledger:
        # the V2 projection has no signed adopted opening receipt. Until the
        # exact baseline migration exists, never let a V2 SELL of legacy
        # inventory poison the post-cutover journal.
        if v1_inventory(root,account):
            return False
        if not signed_v1_worker_stopped():
            return False
        owner=inspect_ownership(root,broker,account)
        if owner.get("owner")!="V2":
            return False
        # An empty V2 journal is initialized ONLY for the already
        # exclusively V2-owned account, with fresh signed V1 inheritance.
        from .store import EventStore
        EventStore(root/"v2/events.sqlite3")
        v2_inventory(root,account)
        return True
    except Exception:return False

class SignedRobinhoodScan:
    provider_id="robinhood_crypto"
    def __init__(self,root,account,proof):
        from robinhood_policy import read_policy
        from robinhood_crypto_execution import RobinhoodCryptoTradingAdapter
        from .robinhood_live_adapter import RobinhoodLiveAdapter
        from .autonomous_live import AutonomousLiveScan
        from .ai_service import SharedAIReviewer
        from .ollama_transport import OllamaReviewTransport
        from .public_crypto import fetch_ticker
        from unified_config import settings
        self.root=Path(root);self.account=account;self.proof=proof
        policy=read_policy(self.root)
        if policy.get("enabled") is not True or policy.get("account")!=account:
            raise ValueError("EXPLICIT_OPERATOR_LIVE_PERMISSION_REQUIRED")
        live=RobinhoodCryptoTradingAdapter.from_state_authorized(self.root,policy)
        inventory,projection=merged_bot_inventory(self.root,account)
        if v1_inventory(self.root,account):
            raise ValueError("V1_MANAGED_LOTS_NEED_SIGNED_ADOPTION_BEFORE_V2")
        # A broker-held external asset is still counted in exposure and
        # never becomes a bot-owned SELL lot.
        def adapter(symbol):
            return RobinhoodLiveAdapter(live,account,policy,symbol,
                verified_managed_positions=inventory,
                public_trade_feed=fetch_ticker)
        cfg=settings(self.root)
        model=cfg.get("ai_model")
        endpoint=cfg.get("ollama_url")
        reviewer=SharedAIReviewer(OllamaReviewTransport(endpoint,model),
              model=model,timeout_seconds=18,ttl_seconds=45)
        def signed_quote(symbol):
            return adapter(symbol).quote()
        def loss_provider(_account):
            from robinhood_order_journal import OrderJournal
            journal=OrderJournal(self.root)
            # Preflight already matched V1 FILLED economics to signed broker.
            rows=journal.load()["orders"]
            now=datetime.now(timezone.utc)
            for row in rows:
                if (isinstance(row,dict) and row.get("account")==account
                    and row.get("side")=="sell" and row.get("status")=="filled"):
                    raw=row.get("filled_at")
                    when=utc(datetime.fromisoformat(raw.replace("Z","+00:00")))
                    if when.date()==now.date():
                        amount(row.get("fee_charged"),"verified sell fee")
                        pnl=Decimal(str(row.get("realized_pnl_usd")))
                        if not pnl.is_finite() or row.get("fee_verified") is False:
                            raise ValueError("V1_CURRENT_DAILY_SELL_LOSS_UNVERIFIED")
            v1=journal.daily_realized_pnl(now)
            v2=Decimal(projection["realized_net_by_reconciled_utc_day"].get(
                 now.date().isoformat(),"0"))
            return max(Decimal("0"),-(v1+v2))
        def exit_lot(symbol,signed_account):
            old=v1_inventory(self.root,account)
            if symbol in old:
                return managed_v1_lot(self.root,"robinhood_crypto",account,
                                     symbol,signed_account)
            item=projection["verified_v2_inventory"].get(symbol)
            if not isinstance(item,dict):
                raise ValueError("MANAGED_EXIT_INVENTORY_MISSING")
            qty=amount(item.get("quantity"),"V2 managed quantity",False)
            from robinhood_exit_tracker import ExitTracker
            tracker=ExitTracker(self.root/"v2")
            observed=signed_quote(symbol)
            opened=utc(datetime.fromisoformat(item["opened_at"]))
            entry={"quantity":str(qty),"average_unit_cost":item["cost_basis"],
                   "opened_at":opened.isoformat(),"cost_basis_verified":True}
            tracker.update(account,{symbol:entry},{symbol:observed.bid})
            peak=tracker.peak(account,symbol,entry)
            return ManagedExitLot(symbol,qty,qty,
                  amount(item["cost_basis"],"V2 verified cost basis",False),
                  opened,high_water_bid=peak,
                  cost_basis_broker_verified=True,
                  original_fills_reconciled=True,
                  same_day_filled_buy=opened.date()==datetime.now(timezone.utc).date())
        class AccountMultiplexer:
            provider_id="robinhood_crypto"
            def account(self,account_id):
                return adapter("BTC-USD").account(account_id)
            def account_for_symbol(self,account_id,symbol):
                if symbol not in _SUPPORTED:
                    raise ValueError("V2_UNSUPPORTED_CRYPTO_PAIR_CAPABILITY")
                return adapter(symbol).account(account_id)
            def find_order(self,key):
                return adapter("BTC-USD").find_order(key)
            def submit(self,intent):
                if intent.symbol not in _SUPPORTED:
                    raise ValueError("V2_UNSUPPORTED_SIGNED_CRYPTO_ORDER")
                return adapter(intent.symbol).submit(intent)
        # One account-scoped scanner checks ALL managed exits before entry.
        # A symbol-specific adapter cannot submit an exit for another coin.
        self.scan=AutonomousLiveScan(
          AccountMultiplexer(),account,state_dir=self.root,
          symbols=list(_SUPPORTED),asset_class=AssetClass.CRYPTO,
          candle_feed=lambda sym,root=self.root:closed_crypto_bars(root,sym),
          quote_feed=signed_quote,gate=lambda:self.proof,
          reviewer=reviewer,realized_loss_provider=loss_provider,
          strategy_parity_provider=lambda:verified_robinhood_parity(
              self.root,"robinhood_crypto",account),
          exit_evidence_provider=exit_lot,
          exit_policy_provider=lambda _:legacy_exit_policy(
              self.root,"robinhood_crypto",account))
    def run_once(self):
        outcome=self.scan.run_once()
        return {"broker":self.provider_id,"state":outcome["state"],
                "reason":"SIGNED_V2_CRYPTO_SCAN_COMPLETED"}

def scanner_factory(root,broker,account,proof):
    if broker!="robinhood_crypto":raise ValueError("BROKER_EXECUTION_NOT_WIRED")
    return SignedRobinhoodScan(root,account,proof)
