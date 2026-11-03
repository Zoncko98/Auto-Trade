"""Durable account-scoped Robinhood order journal and verified cost basis."""
import json,os,tempfile
from datetime import datetime,timezone
from decimal import Decimal,InvalidOperation
from pathlib import Path

FINAL={"filled","canceled","cancelled","failed","rejected","expired"}

class UnreconciledOrder(RuntimeError):pass

def _dec(value,positive=False):
    try:value=Decimal(str(value))
    except (InvalidOperation,ValueError,TypeError):return None
    if not value.is_finite() or value<0 or (positive and value<=0):return None
    return value

def _signed_dec(value):
    try:value=Decimal(str(value))
    except (InvalidOperation,ValueError,TypeError):return None
    return value if value.is_finite() else None

def _timestamp(value):
    if not isinstance(value,str):return None
    try:
        parsed=datetime.fromisoformat(value.replace("Z","+00:00"))
        return parsed if parsed.tzinfo is not None else None
    except (ValueError,TypeError):return None

class OrderJournal:
    def __init__(self,root):
        self.path=Path(root)/"robinhood"/"order_intents.json"
    def load(self):
        try:doc=json.loads(self.path.read_text())
        except FileNotFoundError:return {"version":1,"orders":[]}
        if not isinstance(doc,dict) or doc.get("version")!=1 or not isinstance(doc.get("orders"),list):
            raise UnreconciledOrder("Invalid order journal")
        return doc
    def _save(self,doc):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        fd,temp=tempfile.mkstemp(prefix=".order-",dir=self.path.parent)
        try:
            with os.fdopen(fd,"w") as f:
                os.fchmod(f.fileno(),0o600)
                json.dump(doc,f)
                f.flush();os.fsync(f.fileno())
            os.replace(temp,self.path)
        finally:
            if os.path.exists(temp):os.unlink(temp)
    def pending(self):
        return [row for row in self.load()["orders"] if row.get("status") not in FINAL]
    def record_intent(self,account,client_id,symbol,quantity,limit_price,side="buy"):
        if side not in ("buy","sell"):raise UnreconciledOrder("Unsupported order side")
        doc=self.load()
        if self.pending():raise UnreconciledOrder("Existing order not reconciled")
        if any(row.get("client_order_id")==client_id for row in doc["orders"]):
            raise UnreconciledOrder("Duplicate client order identifier")
        doc["orders"].append({"account":account,"client_order_id":client_id,
            "symbol":symbol,"side":side,"quantity":str(quantity),"limit_price":str(limit_price),
            "status":"intent_unconfirmed"})
        self._save(doc)

    @staticmethod
    def _fill_details(match):
        executions=match.get("executions") if isinstance(match.get("executions"),list) else []
        ex=[]
        for item in executions:
            if not isinstance(item,dict):continue
            qty=_dec(item.get("quantity"),positive=True)
            price=_dec(item.get("effective_price"),positive=True)
            if qty is not None and price is not None:ex.append((qty,price,item.get("timestamp")))
        qty=_dec(match.get("filled_asset_quantity"),positive=True)
        if qty is None and ex:qty=sum((q for q,_,_ in ex),Decimal("0"))
        price=_dec(match.get("average_price"),positive=True)
        if price is None and ex:
            total=sum((q*p for q,p,_ in ex),Decimal("0"))
            count=sum((q for q,_,_ in ex),Decimal("0"))
            if count>0:price=total/count
        fee=_dec(match.get("fee_charged"))
        times=[_timestamp(t) for _,_,t in ex]
        times=[t for t in times if t is not None]
        filled_at=max(times).isoformat() if times else (
            match.get("updated_at") if _timestamp(match.get("updated_at")) else
            match.get("created_at") if _timestamp(match.get("created_at")) else None)
        return qty,price,fee,filled_at

    def _recompute_realized(self,doc):
        positions={}
        for row in doc["orders"]:
            row.pop("realized_pnl_usd",None)
            if row.get("status")!="filled":continue
            qty=_dec(row.get("filled_quantity"),positive=True)
            price=_dec(row.get("average_fill_price"),positive=True)
            if qty is None or price is None:continue
            fee=_dec(row.get("fee_charged"))
            fee=fee if fee is not None else Decimal("0")
            symbol=row.get("symbol")
            if not isinstance(symbol,str):continue
            state=positions.setdefault(symbol,{"quantity":Decimal("0"),"cost":Decimal("0"),
                                               "opened_at":None,"verified":True})
            if row.get("side","buy")=="buy":
                if state["quantity"]==0:state["opened_at"]=row.get("filled_at")
                state["quantity"]+=qty
                state["cost"]+=qty*price+fee
                # Average fill price and filled quantity establish cost basis.
                # A missing fee is handled conservatively by the exit fee buffer.
            elif row.get("side")=="sell":
                if state["quantity"]<=0 or qty>state["quantity"]:
                    state["verified"]=False
                    continue
                unit=state["cost"]/state["quantity"]
                proceeds=qty*price-fee
                pnl=proceeds-unit*qty
                row["realized_pnl_usd"]=str(pnl)
                row["cost_basis_unit_usd"]=str(unit)
                # Average fill price and filled quantity establish cost basis.
                # A missing fee is handled conservatively by the exit fee buffer.
                state["quantity"]-=qty
                state["cost"]-=unit*qty
                if state["quantity"]==0:
                    state["cost"]=Decimal("0");state["opened_at"]=None
        return positions

    def reconcile(self,account,broker_rows):
        if not isinstance(broker_rows,list):raise UnreconciledOrder("Broker order list missing")
        doc=self.load()
        by_id={row.get("client_order_id"):row for row in broker_rows if isinstance(row,dict)}
        for row in doc["orders"]:
            if row["account"]!=account:continue
            match=by_id.get(row["client_order_id"])
            if match is None:continue
            status=str(match.get("state",match.get("status",""))).lower()
            if status=="filled":
                qty,price,fee,filled_at=self._fill_details(match)
                if qty is None or price is None:continue
                row["filled_quantity"]=str(qty)
                row["average_fill_price"]=str(price)
                row["fee_charged"]=str(fee) if fee is not None else "0"
                row["fee_verified"]=fee is not None
                if filled_at:row["filled_at"]=filled_at
            if status in FINAL:row["status"]=status
        self._recompute_realized(doc)
        self._save(doc)
        return len(self.pending())==0

    def positions(self):
        doc=self.load()
        states=self._recompute_realized(doc)
        result={}
        for symbol,state in states.items():
            if state["quantity"]<=0:continue
            result[symbol]={"quantity":state["quantity"],
                "average_unit_cost":state["cost"]/state["quantity"],
                "opened_at":state["opened_at"],"cost_basis_verified":state["verified"]}
        return result

    def daily_realized_pnl(self,now=None):
        now=now or datetime.now(timezone.utc)
        if now.tzinfo is None:raise ValueError("Timezone-aware time required")
        total=Decimal("0")
        for row in self.load()["orders"]:
            if row.get("side")!="sell" or row.get("status")!="filled":continue
            when=_timestamp(row.get("filled_at"))
            pnl=_signed_dec(row.get("realized_pnl_usd"))
            if when is not None and pnl is not None and when.astimezone(timezone.utc).date()==now.astimezone(timezone.utc).date():
                total+=pnl
        return total

    def last_exit_at(self,symbol):
        times=[_timestamp(row.get("filled_at")) for row in self.load()["orders"]
               if row.get("symbol")==symbol and row.get("side")=="sell" and row.get("status")=="filled"]
        times=[t for t in times if t is not None]
        return max(times) if times else None
