"""Virtual brokerage interface backed by the existing paper_account.json ledger."""
import json,os,tempfile,threading
from decimal import Decimal
from pathlib import Path
from broker_workspace import BrokerNotAvailable

class PaperBrokerAdapter:
    provider_id="paper"
    account_ref="paper-primary"
    _lock=threading.RLock()
    def __init__(self,state_dir,quote_provider=None,initial_cash=100):
        self.path=Path(state_dir)/"paper_account.json"
        self.initial=float(initial_cash)
        self.quote_provider=quote_provider
    def _check(self,ref):
        if ref!=self.account_ref:raise BrokerNotAvailable("Unknown paper account")
    def _read(self):
        try:
            obj=json.loads(self.path.read_text())
        except FileNotFoundError:
            obj={"schema":1,"cash":self.initial,"positions":{},"history":{},
                 "last_processed":{},"trades":[],"reviews":[]}
        if obj.get("schema")!=1:raise ValueError("Unknown paper ledger schema")
        return obj
    def _save(self,obj):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        fd,name=tempfile.mkstemp(prefix=".paper-",dir=self.path.parent)
        try:
            with os.fdopen(fd,"w") as handle:
                os.fchmod(handle.fileno(),0o600)
                json.dump(obj,handle,allow_nan=False)
                handle.flush();os.fsync(handle.fileno())
            os.replace(name,self.path)
        finally:
            if os.path.exists(name):os.unlink(name)
    def list_accounts(self):
        return [{"id":self.account_ref,"provider":"paper","type":"virtual","currency":"USD"}]
    def balances(self,account_ref):
        self._check(account_ref)
        with self._lock:
            s=self._read()
            return {"cash":format(Decimal(str(s["cash"])), ".2f"),"currency":"USD","paper_only":True}
    def positions(self,account_ref):
        self._check(account_ref)
        with self._lock:
            return [{"symbol":sym,**pos} for sym,pos in self._read()["positions"].items()]
    def orders(self,account_ref):
        self._check(account_ref)
        with self._lock:
            return list(self._read()["trades"])
    def quote(self,symbol):
        from paper_market_data import recent_quote
        return (self.quote_provider or recent_quote)(symbol)
    def cancel_order(self,account_ref,order_ref):
        self._check(account_ref)
        raise BrokerNotAvailable("Paper fills are immediate and cannot be cancelled")
    def submit_order(self,account_ref,intent):
        """Only virtual fills; intent is produced by shared trading engine."""
        self._check(account_ref)
        if not isinstance(intent,dict) or set(intent)!={"symbol","side","quantity","client_order_id"}:
            raise ValueError("Invalid paper order intent")
        sym=intent["symbol"];side=intent["side"];key=intent["client_order_id"]
        from autonomous_selector import UNIVERSE
        if sym not in set(UNIVERSE)|{"SPY","QQQ","AAPL","MSFT","BTCUSD","ETHUSD"}:
            raise ValueError("Unsupported paper symbol")
        if side not in ("BUY","SELL"):raise ValueError("Unsupported side")
        if not isinstance(key,str) or not 1<=len(key)<=80 or not key.isascii():
            raise ValueError("Invalid idempotency key")
        try:qty=Decimal(str(intent["quantity"]))
        except Exception:raise ValueError("Invalid paper quantity") from None
        if not qty.is_finite() or qty<=0 or qty>1000000:raise ValueError("Invalid paper quantity")
        with self._lock:
            state=self._read()
            for row in state["trades"]:
                if row.get("client_order_id")==key:
                    if row["symbol"]!=sym or row["action"]!=("PAPER_"+side):
                        raise ValueError("Conflicting idempotency key")
                    if Decimal(str(row["quantity"]))!=qty:raise ValueError("Conflicting quantity")
                    return dict(row)
            observation=self.quote(sym)
            price=Decimal(str(observation.get("ask" if side=="BUY" else "bid",observation["price"])))
            if not price.is_finite() or price<=0:raise ValueError("Invalid quote")
            value=(qty*price).quantize(Decimal("0.01"))
            cash=Decimal(str(state["cash"]))
            held=Decimal(str(state["positions"].get(sym,{}).get("quantity",0)))
            if side=="BUY" and value>cash:raise ValueError("Insufficient virtual cash")
            if side=="SELL" and qty>held:raise ValueError("Insufficient virtual holdings")
            state["cash"]=float(cash-value if side=="BUY" else cash+value)
            positions=state["positions"]
            previous=positions.get(sym,{})
            if side=="BUY":
                old_cost=Decimal(str(previous.get("entry_price",price)))*held
                positions[sym]={"quantity":float(held+qty),
                    "entry_price":float((old_cost+value)/(held+qty))}
            elif held==qty:
                positions.pop(sym,None)
            else:
                positions[sym]={"quantity":float(held-qty),
                    "entry_price":float(previous["entry_price"])}
            state.setdefault("history",{}).setdefault(sym,[]).append({
                "timestamp":observation["timestamp"],"price":float(price)})
            state["history"][sym]=state["history"][sym][-6:]
            state.setdefault("last_processed",{})[sym]=observation["timestamp"]
            row={"action":"PAPER_"+side,"symbol":sym,
                 "price":float(price),"quantity":float(qty),
                 "timestamp":observation["timestamp"],"client_order_id":key,
                 "status":"FILLED_SIMULATED","reason":"Shared engine strategy decision",
                 "paper_only":True}
            state["trades"].append(row)
            self._save(state)
            return dict(row)
    def record_review(self,symbol,now,decision,reason):
        with self._lock:
            state=self._read()
            state.setdefault("reviews",[]).append({
                "timestamp":now.isoformat(),"symbol":symbol,
                "approved":decision=="APPROVED","model":"shared_strategy",
                "reason":str(reason)[:400],"risk_flags":[],
                "action":"PAPER_BUY","paper_only":True})
            self._save(state)
