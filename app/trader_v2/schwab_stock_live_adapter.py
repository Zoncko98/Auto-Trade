"""Schwab stock V2 canonical signed adapter, same raw-account writer lock as V1.

The canonical ID is a digest alias of Schwab's account hash; the actual
writer_scope_account is the raw Schwab hash that the existing V1 worker locks.
No implicit operator permission, no short/fractional/margin debt orders.
Unknown POST results remain UNKNOWN until exact signed order ID is known.
"""
from __future__ import annotations
from datetime import datetime,timezone,timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from .models import (Account,Capability,AssetClass,AuthState,
                     OrderSide,OrderIntent,MarketSnapshot,utc,amount)
from .contracts import BrokerExecution
from .live_pipeline import LiveMigrationRejected
from .readonly_adapters import private_json

class SchwabLiveBlocked(RuntimeError):
    def __init__(self,code):
        self.code=code
        super().__init__(code)

def account_alias(hashvalue):
    from .writer_ownership import ACCOUNT
    if (not isinstance(hashvalue,str) or ACCOUNT.fullmatch(hashvalue) is None or
        ".." in hashvalue):
        raise SchwabLiveBlocked("SCHWAB_RAW_ACCOUNT_HASH_UNVERIFIED")
    return "schwab_"+sha256(("v2-journal|"+hashvalue).encode()).hexdigest()[:40]

def _receipt(key,raw,id):
    if (not isinstance(raw,dict) or str(raw.get("orderId"))!=str(id) or
        not str(id).isdigit()):
        raise SchwabLiveBlocked("SIGNED_SCHWAB_RECEIPT_ID_MISMATCH")
    status=str(raw.get("status","")).upper()
    accepted={"QUEUED","WORKING","PENDING_ACTIVATION","ACCEPTED","AWAITING_PARENT_ORDER",
              "AWAITING_CONDITION","PENDING_ACKNOWLEDGEMENT"}
    canceled={"CANCELED","EXPIRED"}
    rejected={"REJECTED"}
    if status not in accepted|{"FILLED","PARTIALLY_FILLED"}|canceled|rejected:
        raise SchwabLiveBlocked("SIGNED_SCHWAB_RECEIPT_STATE_UNVERIFIED")
    try:qty=amount(str(raw.get("filledQuantity","0")),"filled stock qty")
    except (TypeError,ValueError):
        raise SchwabLiveBlocked("SIGNED_SCHWAB_FILL_QTY_UNVERIFIED") from None
    filled=qty>0
    if (status=="FILLED" and not filled or
        status=="PARTIALLY_FILLED" and not filled):
        raise SchwabLiveBlocked("SIGNED_SCHWAB_FINAL_FILL_CONTRADICTORY")
    if filled:
        # Never infer zero fees or completed legs from quote/limit price.
        legs=[];fees=Decimal("0");explicit_fee=False
        for item in raw.get("orderActivityCollection") or []:
            if not isinstance(item,dict):raise SchwabLiveBlocked("SIGNED_SCHWAB_ACTIVITY_INVALID")
            for leg in item.get("executionLegs") or []:
                if not isinstance(leg,dict):
                    raise SchwabLiveBlocked("SIGNED_SCHWAB_EXECUTION_LEGS_INVALID")
                try:
                    q=amount(str(leg["quantity"]),"executed shares",False)
                    p=amount(str(leg["price"]),"executed price",False)
                except (KeyError,TypeError,ValueError):
                    raise SchwabLiveBlocked("SIGNED_SCHWAB_EXECUTION_LEGS_INVALID") from None
                legs.append((q,p))
                for field in ("fee","fees","commission"):
                    if field in leg and leg[field] is not None:
                        fees+=amount(str(leg[field]),"signed fee")
                        explicit_fee=True
            for field in ("fee","fees","commission"):
                if field in item and item[field] is not None:
                    fees+=amount(str(item[field]),"signed fee")
                    explicit_fee=True
        if sum((q for q,p in legs),Decimal("0"))!=qty:
            raise SchwabLiveBlocked("SIGNED_SCHWAB_EXECUTION_QUANTITY_MISMATCH")
        if not explicit_fee:
            raise SchwabLiveBlocked("SIGNED_SCHWAB_FEE_EVIDENCE_REQUIRED")
        avg=sum((q*p for q,p in legs),Decimal("0"))/qty
    else:avg=fees=Decimal("0")
    state=("FILLED" if status=="FILLED" else
           "CANCELED" if status in canceled else
           "REJECTED" if status in rejected else
           "PARTIALLY_FILLED" if status=="PARTIALLY_FILLED" or filled
           else "BROKER_ACCEPTED")
    return BrokerExecution(key,state,str(id),qty,avg,fees)

class SchwabStockLiveAdapter:
    provider_id="schwab"
    def __init__(self,signed_client,account_hash,*,state_dir,operator_authorized=False,
                 managed_positions=None,clock=None,order_builder=None,
                 order_id_extractor=None,event_store=None):
        self.writer_scope_account=account_hash
        self.account_id=account_alias(account_hash)
        self.client=signed_client
        self.state=Path(state_dir)
        self.operator_authorized=operator_authorized is True
        self.managed=dict(managed_positions or {})
        self.clock=clock or (lambda:datetime.now(timezone.utc))
        self.order_builder=order_builder
        self.order_id_extractor=order_id_extractor
        self.store=event_store
    def _verified(self):
        from live_worker import confirm_account
        from live_order_safety import position_snapshot,verified_cash,equity_value
        try:
            signed=confirm_account(self.client,self.writer_scope_account)
            actual,exposure=position_snapshot(signed)
            cash=verified_cash(signed)
            equity=equity_value(signed)
            if equity<cash or equity+Decimal("0.01")<exposure:
                raise ValueError
            return actual,exposure,cash,equity
        except Exception:
            raise SchwabLiveBlocked("SIGNED_SCHWAB_ACCOUNT_HOLDINGS_OR_CASH_UNVERIFIED") from None
    def account(self,account_id):
        if account_id!=self.account_id:
            raise SchwabLiveBlocked("SCHWAB_CANONICAL_ACCOUNT_MISMATCH")
        actual,exposure,cash,equity=self._verified()
        managed={}
        for sym,qty in self.managed.items():
            try:v=amount(qty,"verified managed shares")
            except (TypeError,ValueError):
                raise SchwabLiveBlocked("SCHWAB_BOT_POSITION_UNVERIFIED") from None
            if v!=v.to_integral_value() or v>actual.get(sym,0):
                raise SchwabLiveBlocked("SCHWAB_BOT_POSITION_EXCEEDS_SIGNED_HOLDINGS")
            if v>0:managed[sym]=v
        return Account(self.account_id,self.provider_id,
            Capability(frozenset({AssetClass.STOCK}),fractional=False,
                       min_notional=Decimal("1"),quantity_increment=Decimal("1"),
                       price_increment=Decimal("0.01")),
            cash,equity,managed,AuthState.CONNECTED,
            self.operator_authorized,exposure)
    def _session(self,now):
        from live_worker import market_is_normal
        try:return market_is_normal(self.client,now)
        except Exception:return False
    def quote(self,symbol,*,now=None):
        from live_worker import result
        from live_order_safety import quote_levels
        now=utc(now or self.clock())
        if not self._session(now):
            raise SchwabLiveBlocked("SCHWAB_SIGNED_STOCK_MARKET_SESSION_CLOSED")
        try:
            doc=result(self.client.get_quote(symbol),"signed stock quote")
            raw=doc.get(symbol)
            bid,ask=quote_levels(raw,now)
            detail=raw["quote"]
            observed=datetime.fromtimestamp(
                int(detail["quoteTime"])/1000,timezone.utc)
            last=amount(str(detail["lastPrice"]),"signed Schwab last",False)
            if (now-observed).total_seconds()>30:
                raise ValueError
            return MarketSnapshot(symbol,AssetClass.STOCK,"schwab_signed",
                observed,now,bid,ask,last,True)
        except Exception:
            raise SchwabLiveBlocked("SIGNED_SCHWAB_STOCK_QUOTE_UNVERIFIED") from None
    def _risk_controls(self,side,now):
        from live_extension import read_live_risk
        try:
            settings=read_live_risk(self.state)["settings"]
            # Existing V1 journal remains an independent acceptance input.
            journal=private_json(self.state/"live/orders.json",maximum=3_000_000)
            if not journal or not isinstance(journal.get("orders"),list):
                raise ValueError
            from zoneinfo import ZoneInfo
            day=now.astimezone(ZoneInfo("America/New_York")).date()
            actions=0;buys=0;sells=0;settlement=False
            for order in journal["orders"]:
                if not isinstance(order,dict):raise ValueError
                created=datetime.fromisoformat(order["created_at"].replace("Z","+00:00"))
                if created.tzinfo is None:raise ValueError
                if created.astimezone(ZoneInfo("America/New_York")).date()==day:
                    actions+=1;buys+=order.get("action")=="BUY";sells+=order.get("action")=="SELL"
                if (order.get("action")=="SELL" and order.get("state")=="FILLED"
                    and (now-created).total_seconds()<86400):
                    settlement=True
            if side is OrderSide.BUY and (buys>=settings["max_buys_per_day"] or
                                          actions>=settings["max_orders_per_day"] or settlement):
                raise SchwabLiveBlocked("SCHWAB_V1_ENTRY_LIMIT_OR_SETTLEMENT")
            if side is OrderSide.SELL and sells>=settings["max_exit_orders_per_day"]:
                raise SchwabLiveBlocked("SCHWAB_V1_EXIT_ORDER_LIMIT")
            return settings
        except SchwabLiveBlocked:raise
        except Exception:
            raise SchwabLiveBlocked("SCHWAB_V1_RISK_OR_ORDER_HISTORY_UNVERIFIED") from None
    def find_order(self,key):
        if self.store is None:return None
        try:events=self.store.events(key)
        except Exception:return None
        ids={ev["evidence"].get("broker_order_id") for ev in events
             if ev.get("state")=="BROKER_ACCEPTED"
             and isinstance(ev.get("evidence"),dict)
             and ev["evidence"].get("broker_order_id")}
        if len(ids)!=1:return None
        oid=next(iter(ids))
        if not str(oid).isdigit():return None
        from live_worker import result
        try:
            raw=result(self.client.get_order(int(oid),self.writer_scope_account),
                       "original signed order status")
            return _receipt(key,raw,oid)
        except Exception:
            return None
    def submit(self,intent:OrderIntent)->BrokerExecution:
        if (not self.operator_authorized or
            not isinstance(intent,OrderIntent) or
            intent.account_id!=self.account_id or
            intent.asset_class is not AssetClass.STOCK or
            intent.quantity!=intent.quantity.to_integral_value() or
            intent.limit_price!=intent.limit_price.quantize(Decimal("0.01"))):
            raise LiveMigrationRejected("SCHWAB_V2_ORDER_IDENTITY_OR_AUTHORITY_INVALID")
        now=utc(self.clock())
        if not self._session(now):
            raise LiveMigrationRejected("SCHWAB_BROKER_MARKET_SESSION_CLOSED")
        settings=self._risk_controls(intent.side,now)
        actual,exposure,cash,equity=self._verified()
        if intent.side is OrderSide.SELL:
            bot=amount(self.managed.get(intent.symbol,Decimal("0")),"verified owned qty")
            if not 0<intent.quantity<=min(Decimal(actual.get(intent.symbol,0)),bot):
                raise LiveMigrationRejected("SCHWAB_BOT_INVENTORY_NOT_VERIFIED")
        else:
            capital=min(equity,Decimal(str(settings["strategy_capital_usd"])))
            cap=min(Decimal(str(settings["max_order_usd"])),
                    cash*Decimal(str(settings["allocation_pct"]))/100,
                    capital*Decimal(str(settings["max_position_pct"]))/100)
            if (intent.quantity*intent.limit_price>cap or
                intent.symbol in actual or
                len(actual)>=settings["max_open_positions"]):
                raise LiveMigrationRejected("SCHWAB_ENTRY_EXCEEDS_CAPITAL_OR_POSITION_LIMIT")
        from live_worker import current_broker_orders
        from live_order_safety import OPEN_STATUSES
        try:orders=current_broker_orders(self.client,self.writer_scope_account)
        except Exception:
            raise LiveMigrationRejected("SCHWAB_SIGNED_ORDER_HISTORY_UNAVAILABLE") from None
        if any(isinstance(o,dict) and o.get("status") in OPEN_STATUSES for o in orders):
            raise LiveMigrationRejected("SCHWAB_BROKER_OPEN_ORDERS")
        quote=self.quote(intent.symbol,now=now)
        if intent.side is OrderSide.BUY:
            if intent.limit_price<quote.ask or (
                intent.limit_price/quote.ask-1)>Decimal("0.005"):
                raise LiveMigrationRejected("SCHWAB_BUY_LIMIT_MOVED")
        else:
            if intent.limit_price>quote.bid or (
                1-intent.limit_price/quote.bid)>Decimal("0.005"):
                raise LiveMigrationRejected("SCHWAB_SELL_LIMIT_MOVED")
        if self.order_builder is not None:
            order=self.order_builder(intent.side,intent.symbol,
                                      int(intent.quantity),intent.limit_price)
        else:
            from schwab.orders.equities import equity_buy_limit,equity_sell_limit
            builder=(equity_buy_limit if intent.side is OrderSide.BUY else equity_sell_limit)
            order=builder(intent.symbol,int(intent.quantity),
                          float(intent.limit_price)).build()
        # LivePipeline persists SUBMITTING under the same raw account writer
        # lock BEFORE this single broker POST. Never retry a timeout.
        response=self.client.place_order(self.writer_scope_account,order)
        if getattr(response,"status_code",None) not in (200,201):
            raise SchwabLiveBlocked("SCHWAB_POST_OUTCOME_UNVERIFIED")
        if self.order_id_extractor is not None:
            oid=self.order_id_extractor(response)
        else:
            from schwab.utils import Utils
            oid=Utils(self.client,self.writer_scope_account).extract_order_id(response)
        if not isinstance(oid,(str,int)) or not str(oid).isdigit():
            raise SchwabLiveBlocked("SCHWAB_ORDER_ID_UNAVAILABLE_RECONCILE_MANUALLY")
        return BrokerExecution(intent.key,"BROKER_ACCEPTED",str(oid),
                               Decimal("0"),Decimal("0"),Decimal("0"))
