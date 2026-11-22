"""V2 Webull stock adapter using the original signed SDK and account limits.

No separate app, no implicit account selection. Only LivePipeline may call
submit after durable V2 intent, AI/risk review and exclusive V2 writer lock.
Signed GET preflight is rechecked immediately before every broker POST.
"""
from __future__ import annotations
from datetime import datetime,timezone
from decimal import Decimal
from .models import (Account,Capability,AssetClass,AuthState,MarketSnapshot,
                     OrderSide,OrderIntent,amount,utc)
from .webull_signed_receipts import (
    WebullReadOnlyReceiptAdapter,client_order_id,WebullReceiptUnverified)
from .live_pipeline import LiveMigrationRejected
from .market_sources import webull_market_quote,MarketSourceError

class WebullLiveBlocked(RuntimeError):
    def __init__(self,code):
        self.code=code
        super().__init__(code)

class WebullStockLiveAdapter:
    provider_id="webull"
    def __init__(self,signed_broker,account_id,policy,risk,managed_positions,
                 *,clock=None,allow_margin_accounts=False):
        if (not isinstance(account_id,str) or not 1<=len(account_id)<=80 or
            not isinstance(policy,dict) or not isinstance(risk,dict) or
            not isinstance(managed_positions,dict)):
            raise ValueError("Account-scoped signed Webull setup required")
        self.broker=signed_broker
        self.account_id=account_id
        self.policy=dict(policy)
        self.risk=dict(risk)
        self.managed=dict(managed_positions)
        self.allow_margin_accounts=allow_margin_accounts is True
        self.clock=clock or (lambda:datetime.now(timezone.utc))
        self.receipts=WebullReadOnlyReceiptAdapter(signed_broker,account_id)
    def _account_config(self):
        if (self.policy.get("enabled") is not True or
            self.policy.get("trade_stocks") is not True or
            self.policy.get("stock_account")!=self.account_id or
            self.policy.get("environment") not in (None,"production")):
            raise WebullLiveBlocked("WEBULL_OPERATOR_POLICY_OR_ACCOUNT_DISARMED")
        try:
            from webull_worker import _can_trade_account
            detail=self.broker.verify_account(self.account_id)
            if not _can_trade_account(detail,"EQUITY",self.allow_margin_accounts):
                raise WebullLiveBlocked("WEBULL_ACCOUNT_CLASS_UNSUPPORTED")
            return detail
        except WebullLiveBlocked:
            raise
        except Exception:
            raise WebullLiveBlocked("SIGNED_WEBULL_ACCOUNT_UNAVAILABLE") from None
    def _balance(self,selected):
        try:
            from webull_worker import _funds,verify_margin_cash_funding,_account_class
            balance=self.broker.balance(self.account_id)
            equity,cash,day_pnl=_funds(balance)
            if "MARGIN" in _account_class(selected):
                cash=min(cash,verify_margin_cash_funding(balance))
            exposure=amount(balance.get("total_market_value"),"broker gross exposure")
            if exposure>equity+Decimal("0.01") or cash>equity+Decimal("0.01"):
                raise ValueError
            return equity,cash,day_pnl,exposure
        except Exception:
            raise WebullLiveBlocked("SIGNED_WEBULL_CASH_EXPOSURE_UNVERIFIED") from None
    def _holdings(self):
        try:positions=self.broker.positions(self.account_id)
        except Exception:
            raise WebullLiveBlocked("SIGNED_WEBULL_HOLDINGS_UNAVAILABLE") from None
        if not isinstance(positions,list):
            raise WebullLiveBlocked("SIGNED_WEBULL_HOLDINGS_UNAVAILABLE")
        actual={}
        for row in positions:
            if (not isinstance(row,dict) or
                row.get("instrument_type")!="EQUITY"):
                raise WebullLiveBlocked("SIGNED_WEBULL_UNSUPPORTED_HELD_ASSET")
            sym=row.get("symbol")
            if not isinstance(sym,str) or not sym:
                raise WebullLiveBlocked("SIGNED_WEBULL_HELD_SYMBOL_INVALID")
            if sym in actual:
                raise WebullLiveBlocked("SIGNED_WEBULL_DUPLICATE_HELD_ASSET")
            try:qty=amount(row.get("quantity"),"broker held stock qty")
            except (ValueError,TypeError):
                raise WebullLiveBlocked("SIGNED_WEBULL_HOLDING_QTY_INVALID") from None
            if qty!=qty.to_integral_value():
                raise WebullLiveBlocked("WEBULL_V2_STOCK_FRACTIONAL_UNSUPPORTED")
            actual[sym]=qty
        return actual
    def account(self,account_id):
        if account_id!=self.account_id:
            raise WebullLiveBlocked("WEBULL_SIGNED_ACCOUNT_MISMATCH")
        selected=self._account_config()
        equity,cash,pnl,exposure=self._balance(selected)
        actual=self._holdings()
        managed={}
        for sym,raw in self.managed.items():
            try:qty=amount(raw,"verified bot owned Webull qty")
            except (TypeError,ValueError):
                raise WebullLiveBlocked("WEBULL_MANAGED_INVENTORY_UNVERIFIED") from None
            if qty>actual.get(sym,Decimal("0")):
                raise WebullLiveBlocked("WEBULL_BOT_INVENTORY_EXCEEDS_BROKER")
            if qty>0:managed[sym]=qty
        return Account(self.account_id,"webull",
            Capability(frozenset({AssetClass.STOCK}),fractional=False,
                       min_notional=Decimal("1"),quantity_increment=Decimal("1"),
                       price_increment=Decimal("0.01")),
            cash,equity,managed,AuthState.CONNECTED,True,exposure)
    def quote(self,symbol,*,now=None):
        now=utc(now or self.clock())
        self._account_config()
        from webull_signals import core_stock_session
        if not core_stock_session(now):
            raise WebullLiveBlocked("WEBULL_CORE_MARKET_SESSION_CLOSED")
        try:
            raw=self.broker.quote(symbol,"EQUITY")
            reading=webull_market_quote(raw,symbol,now=now)
            if not reading.source_tradable:
                raise MarketSourceError("BROKER_QUOTE_UNTRADABLE")
            if reading.last is None:
                snapshot=self.broker.stock_snapshot(symbol)
                # Last trade must be signed and independently timestamped; do
                # not synthesize midpoint/last from bid-ask or receipt time.
                last=snapshot.get("last_price") or snapshot.get("price")
                if last is None:raise ValueError
                from .market_sources import _sourced_time
                _sourced_time(snapshot.get("time") or
                              snapshot.get("quote_time") or
                              snapshot.get("timestamp"),now,ttl=20)
                reading_last=amount(last,"signed stock last",False)
            else:
                reading_last=reading.last
            return MarketSnapshot(symbol,AssetClass.STOCK,"webull_signed",
                reading.observed_at,reading.received_at,reading.bid,
                reading.ask,reading_last,True)
        except (WebullLiveBlocked,MarketSourceError,ValueError,TypeError):
            raise WebullLiveBlocked("SIGNED_WEBULL_EXECUTABLE_QUOTE_UNVERIFIED") from None
        except Exception:
            raise WebullLiveBlocked("SIGNED_WEBULL_QUOTE_GET_UNAVAILABLE") from None
    def find_order(self,key):
        return self.receipts.find_order(key)
    def submit(self,intent:OrderIntent):
        from webull_worker import _funds
        from webull_signals import core_stock_session
        if (not isinstance(intent,OrderIntent) or
            intent.asset_class is not AssetClass.STOCK or
            intent.account_id!=self.account_id or
            intent.side not in (OrderSide.BUY,OrderSide.SELL) or
            intent.quantity!=intent.quantity.to_integral_value()):
            raise LiveMigrationRejected("WEBULL_V2_ORDER_IDENTITY_UNVERIFIED")
        now=utc(self.clock())
        if not core_stock_session(now):
            raise LiveMigrationRejected("WEBULL_MARKET_SESSION_CLOSED")
        selected=self._account_config()
        equity,cash,day_pnl,exposure=self._balance(selected)
        loss=amount(self.risk.get("max_daily_loss_usd"),"Webull daily loss",False)
        max_order=amount(self.risk.get("max_order_usd"),"Webull max order",False)
        pct=amount(str(self.risk.get("max_position_pct")),"Webull position percent",False)
        max_positions=self.risk.get("max_open_positions")
        if (loss>Decimal("250") or max_order>Decimal("1000") or
            pct>Decimal("10") or type(max_positions) is not int or
            not 1<=max_positions<=10):
            raise LiveMigrationRejected("WEBULL_POLICY_OUTSIDE_HARD_RISK_LIMIT")
        if day_pnl<=-loss:
            raise LiveMigrationRejected("WEBULL_DAILY_LOSS_LIMIT")
        if self.broker.open_orders(self.account_id):
            raise LiveMigrationRejected("WEBULL_BROKER_PENDING_ORDERS")
        current=self.quote(intent.symbol,now=now)
        if intent.side is OrderSide.BUY:
            if (intent.limit_price<current.ask or
                intent.limit_price/current.ask-1>Decimal("0.005")):
                raise LiveMigrationRejected("WEBULL_BUY_PRICE_MOVED")
            if intent.symbol in self._holdings() and self._holdings()[intent.symbol]>0:
                raise LiveMigrationRejected("WEBULL_EXTERNAL_OR_MANAGED_HOLDING_ALREADY_PRESENT")
            if len([x for x in self._holdings().values() if x>0])>=max_positions:
                raise LiveMigrationRejected("WEBULL_OPEN_POSITION_LIMIT")
            notional=intent.quantity*intent.limit_price
            budget=min(max_order,cash*Decimal(".25"),equity*pct/100)
            if (notional>budget or exposure+notional>equity*Decimal(".25")):
                raise LiveMigrationRejected("WEBULL_CASH_OR_EXPOSURE_LIMIT")
        else:
            held=self._holdings().get(intent.symbol,Decimal("0"))
            bot=amount(self.managed.get(intent.symbol,Decimal("0")),
                        "managed confirmed stock position")
            if not 0<intent.quantity<=min(held,bot):
                raise LiveMigrationRejected("WEBULL_NOT_VERIFIED_BOT_EXIT")
            if intent.limit_price>current.bid or (
                1-intent.limit_price/current.bid)>Decimal(".005"):
                raise LiveMigrationRejected("WEBULL_SELL_LIMIT_OUTSIDE_BROKER_BID")
        order_id=client_order_id(intent.key,intent.account_id)
        payload={"combo_type":"NORMAL","client_order_id":order_id,
            "symbol":intent.symbol,"instrument_type":"EQUITY",
            "market":"US","order_type":"LIMIT",
            "limit_price":str(intent.limit_price),
            "quantity":str(intent.quantity),
            "side":intent.side.value,"time_in_force":"DAY",
            "entrust_type":"QTY","support_trading_session":"CORE"}
        # Preview is an actual signed SDK check but NOT a broker order.
        try:pre=self.broker.preview(self.account_id,payload)
        except Exception:
            raise LiveMigrationRejected("WEBULL_ORDER_PREVIEW_UNAVAILABLE") from None
        if not isinstance(pre,dict) or pre.get("success") is False or pre.get("errors") or pre.get("error"):
            raise LiveMigrationRejected("WEBULL_ORDER_PREVIEW_REJECTED")
        # LivePipeline owns the V2 file lock and persisted deterministic intent
        # *before* this single signed POST. Never automatically retry.
        self.broker.place(self.account_id,payload)
        return self.find_order(intent.key)
