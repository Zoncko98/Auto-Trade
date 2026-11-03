"""Official Webull v3 broker adapter. No implicit account selection or orders."""
import re
from decimal import Decimal,InvalidOperation
from webull_openapi import _api,_data,_accounts,WebullError

STOCK=re.compile(r"[A-Z]{1,5}(?:[.-][A-Z]{1,2})?")
CRYPTO=re.compile(r"[A-Z0-9]{2,15}USD")
ASSETS={"EQUITY":STOCK,"CRYPTO":CRYPTO}

def positive(value,allow_zero=False):
    try:d=Decimal(str(value))
    except (InvalidOperation,TypeError,ValueError):raise WebullError("Invalid broker numeric field") from None
    if not d.is_finite() or d<0 or (not allow_zero and d==0):
        raise WebullError("Invalid broker numeric field")
    return d

def _rows(data):
    if isinstance(data,list):return data
    if isinstance(data,dict):
        for key in ("data","orders","list","items","results"):
            rows=data.get(key)
            if isinstance(rows,list):return rows
            if isinstance(rows,dict):
                for field in ("items","orders","data","list"):
                    if isinstance(rows.get(field),list):return rows[field]
    raise WebullError("Unexpected broker list response")

class WebullBroker:
    def __init__(self,state):
        from webull.trade.trade_client import TradeClient
        from webull.data.data_client import DataClient
        api,self.environment=_api(state)
        self.trade=TradeClient(api)
        self.data=DataClient(api)
    def accounts(self):
        rows=_accounts(_data(self.trade.account_v2.get_account_list()))
        if not all(isinstance(x,dict) and isinstance(x.get("account_id"),str) and
                   x["account_id"] for x in rows):
            raise WebullError("Broker account list invalid")
        return rows
    def verify_account(self,account_id):
        if not isinstance(account_id,str) or not account_id or len(account_id)>80:
            raise WebullError("Invalid account selection")
        matched=[a for a in self.accounts() if a["account_id"]==account_id]
        if len(matched)!=1:raise WebullError("Account not independently authenticated")
        return matched[0]
    def balance(self,account):
        self.verify_account(account)
        data=_data(self.trade.account_v2.get_account_balance(account))
        if not isinstance(data,dict) or data.get("total_asset_currency")!="USD":
            raise WebullError("USD balance unavailable")
        return data
    def positions(self,account):
        self.verify_account(account)
        return _rows(_data(self.trade.account_v2.get_account_position(account)))
    def order_detail(self,account,client_id):
        self.verify_account(account)
        if not re.fullmatch("[a-f0-9]{32}",client_id or ""):
            raise WebullError("Invalid client order identifier")
        data=_data(self.trade.order_v3.get_order_detail(account,client_id))
        if not isinstance(data,dict):raise WebullError("Invalid order detail response")
        return data
    def open_orders(self,account):
        self.verify_account(account)
        data=_data(self.trade.order_v3.get_order_open(account_id=account))
        rows=_rows(data)
        # Never assert a complete order list if the broker gave another page.
        if isinstance(data,dict) and data.get("pagination_key"):
            raise WebullError("Broker open orders span pages; execution blocked")
        return rows
    @staticmethod
    def _validate_order(order):
        if set(order)!= set(("combo_type","client_order_id","symbol","instrument_type",
                            "market","order_type","limit_price","quantity","side",
                            "time_in_force","entrust_type")) and set(order)!=set((
                            "combo_type","client_order_id","symbol","instrument_type",
                            "market","order_type","limit_price","quantity","side",
                            "time_in_force","entrust_type","support_trading_session")):
            raise WebullError("Unexpected order payload")
        if order.get("instrument_type") not in ASSETS or not ASSETS[order["instrument_type"]].fullmatch(order["symbol"]):
            raise WebullError("Only USD cash stocks and spot crypto supported")
        if order.get("side") not in ("BUY","SELL") or order.get("order_type")!="LIMIT":
            raise WebullError("Only limit buy/sell supported")
        if order.get("market")!="US" or order.get("time_in_force")!="DAY" or order.get("entrust_type")!="QTY":
            raise WebullError("Order type not permitted")
        if order["instrument_type"]=="EQUITY" and order.get("support_trading_session")!="CORE":
            raise WebullError("Only core session stock orders")
        if order["instrument_type"]=="CRYPTO" and "support_trading_session" in order:
            raise WebullError("Crypto order contains stock session")
        if order.get("combo_type")!="NORMAL" or not re.fullmatch("[a-f0-9]{32}",order.get("client_order_id","")):
            raise WebullError("Unsupported combination or identifier")
        positive(order["quantity"]);positive(order["limit_price"])
    def preview(self,account,order):
        self.verify_account(account)
        self._validate_order(order)
        if order["instrument_type"]!="EQUITY":
            raise WebullError("Webull preview is unsupported for crypto")
        return _data(self.trade.order_v3.preview_order(account,[order]))
    def place(self,account,order):
        self.verify_account(account)
        self._validate_order(order)
        return _data(self.trade.order_v3.place_order(account,[order]))
    def bars(self,symbol,asset):
        if asset=="EQUITY" and STOCK.fullmatch(symbol):
            raw=_data(self.data.market_data.get_history_bar(symbol,"US_STOCK","M1"))
        elif asset=="CRYPTO" and CRYPTO.fullmatch(symbol):
            raw=_data(self.data.crypto_market_data.get_crypto_history_bar(symbol,"US_CRYPTO","M1"))
        else:raise WebullError("Asset not supported for bars")
        candidates=raw if isinstance(raw,list) else [raw]
        matched=[r for r in candidates if isinstance(r,dict) and
                 r.get("symbol")==symbol and isinstance(r.get("result"),list)]
        if len(matched)!=1:raise WebullError("Missing symbol-specific market bars")
        return matched[0]["result"]
    def quote(self,symbol,asset):
        if asset=="CRYPTO" and CRYPTO.fullmatch(symbol):
            raw=_data(self.data.crypto_market_data.get_crypto_snapshot(symbol))
        elif asset=="EQUITY" and STOCK.fullmatch(symbol):
            raw=_data(self.data.market_data.get_quotes(symbol,"US_STOCK",depth=1,overnight_required=False))
        else:raise WebullError("Unsupported quote instrument")
        if isinstance(raw,list):
            rows=[r for r in raw if isinstance(r,dict) and r.get("symbol")==symbol]
            if len(rows)!=1:raise WebullError("Broker quote ambiguous")
            return rows[0]
        if isinstance(raw,dict) and raw.get("symbol")==symbol:
            return raw
        raise WebullError("Broker quote unavailable")
