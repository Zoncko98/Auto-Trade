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
    def stock_api_probe(self):
        """Read-only, minimal AAPL permission probe; no order APIs or credential disclosure."""
        methods={
            "snapshot": lambda:self.data.market_data.get_snapshot("AAPL","US_STOCK"),
            "best_bid_ask": lambda:self.data.market_data.get_quotes(
                "AAPL","US_STOCK",depth=1,overnight_required=False),
            "minute_bars": lambda:self.data.market_data.get_history_bar(
                "AAPL","US_STOCK","M1")}
        result={}
        for label,call in methods.items():
            try:
                response=call()
                code=getattr(response,"status_code",None)
                if isinstance(code,int) and 100<=code<=599:
                    result[label]={"http_status":code,
                                   "status":"OK" if code==200 else "HTTP_"+str(code)}
                    if code==200:
                        # Only a shape summary for public market data.
                        # Never persist Webull response bodies or signed headers.
                        try:
                            body=response.json()
                            shape={"container":type(body).__name__}
                            safe={"symbol","result","data","items","list","bids","asks",
                                   "quote_time","time","close","bars","bid","ask","price","code","msg"}
                            if isinstance(body,dict):
                                shape["fields"]=sorted(safe.intersection(body))
                                child=body.get("data")
                                if isinstance(child,dict):
                                    shape["data_container"]="dict"
                                    shape["data_fields"]=sorted(safe.intersection(child))
                                elif isinstance(child,list):
                                    shape["data_container"]="list"
                                    shape["data_rows"]=len(child)
                                    if child and isinstance(child[0],dict):
                                        shape["data_fields"]=sorted(safe.intersection(child[0]))
                                if isinstance(body.get("result"),list):
                                    shape["result_rows"]=len(body["result"])
                                    if body["result"] and isinstance(body["result"][0],dict):
                                        shape["result_first_fields"]=sorted(
                                            safe.intersection(body["result"][0]))
                                        inner=body["result"][0].get("result")
                                        if isinstance(inner,list):
                                            shape["nested_result_rows"]=len(inner)
                            elif isinstance(body,list):
                                shape["rows"]=len(body)
                                if body and isinstance(body[0],dict):
                                    shape["first_fields"]=sorted(safe.intersection(body[0]))
                            result[label]["schema"]=shape
                        except (ValueError,TypeError,AttributeError):
                            result[label]["schema"]={"container":"unavailable"}
                else:
                    result[label]={"status":"UNEXPECTED_HTTP_RESPONSE"}
            except Exception as exc:
                # Sanitized exception codes only, never signed SDK error text.
                match=re.search(r"HTTP (?:Status: )?([45]\d\d)",str(exc))
                status="HTTP_"+match.group(1) if match else type(exc).__name__.upper()
                result[label]={"status":status if len(status)<=48 else "SDK_ERROR"}
        codes=[row["status"] for row in result.values()]
        if all(x=="OK" for x in codes):
            state="ALL_STOCK_ENDPOINTS_AUTHORIZED"
        elif all(x=="HTTP_403" for x in codes):
            state="ALL_STOCK_ENDPOINTS_FORBIDDEN"
        elif any(x=="OK" for x in codes):
            state="PARTIAL_STOCK_ENDPOINT_ACCESS"
        else:
            state="STOCK_ENDPOINTS_UNVERIFIED"
        return {"state":state,"endpoints":result,
                "symbol":"AAPL","orders_submitted":False}

    def bars(self,symbol,asset):
        if asset=="EQUITY" and STOCK.fullmatch(symbol):
            raw=_data(self.data.market_data.get_history_bar(symbol,"US_STOCK","M1"))
        elif asset=="CRYPTO" and CRYPTO.fullmatch(symbol):
            raw=_data(self.data.crypto_market_data.get_crypto_history_bar(symbol,"US_CRYPTO","M1"))
        else:raise WebullError("Asset not supported for bars")
        # Webull stock M1 currently returns an outer "result" container
        # with one symbol-specific record, while the documented single-symbol
        # response places "symbol" at the top level. Require a unique
        # symbol match; never mix bars from multiple instruments.
        candidates=raw if isinstance(raw,list) else [raw]
        matched=[r for r in candidates if isinstance(r,dict) and
                 r.get("symbol")==symbol and isinstance(r.get("result"),list)]
        if len(matched)==1:
            return matched[0]["result"]
        if len(matched)>1:
            raise WebullError("Missing symbol-specific market bars")
        if isinstance(raw,dict) and raw.get("symbol") in (None,symbol):
            payload=raw.get("result")
            if isinstance(payload,list) and len(payload)==1:
                nested=payload[0]
                if (isinstance(nested,dict) and nested.get("symbol")==symbol
                    and isinstance(nested.get("result"),list)):
                    return nested["result"]
            if (isinstance(payload,list) and payload and
                all(isinstance(row,dict) and "time" in row and "close" in row and
                    row.get("symbol") in (None,symbol) for row in payload)):
                return payload
        if (isinstance(raw,list) and raw and
            all(isinstance(row,dict) and "time" in row and "close" in row and
                row.get("symbol") in (None,symbol) for row in raw)):
            return raw
        raise WebullError("Missing symbol-specific market bars")
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
