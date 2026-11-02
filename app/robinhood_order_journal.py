"""Durable account-scoped Robinhood order-intent journal. No brokerage writes."""
import json,os,tempfile
from pathlib import Path

FINAL={"filled","canceled","cancelled","failed","rejected","expired"}

class UnreconciledOrder(RuntimeError):pass

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
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp,self.path)
        finally:
            if os.path.exists(temp):os.unlink(temp)
    def pending(self):
        return [row for row in self.load()["orders"] if row.get("status") not in FINAL]
    def record_intent(self,account,client_id,symbol,quantity,limit_price):
        doc=self.load()
        if self.pending():raise UnreconciledOrder("Existing order not reconciled")
        if any(row.get("client_order_id")==client_id for row in doc["orders"]):
            raise UnreconciledOrder("Duplicate client order identifier")
        doc["orders"].append({"account":account,"client_order_id":client_id,
            "symbol":symbol,"quantity":str(quantity),"limit_price":str(limit_price),
            "status":"intent_unconfirmed"})
        self._save(doc)
    def reconcile(self,account,broker_rows):
        if not isinstance(broker_rows,list):raise UnreconciledOrder("Broker order list missing")
        doc=self.load()
        by_id={row.get("client_order_id"):row for row in broker_rows if isinstance(row,dict)}
        for row in doc["orders"]:
            if row["account"]!=account:continue
            match=by_id.get(row["client_order_id"])
            if match is None:continue
            status=str(match.get("state",match.get("status",""))).lower()
            if status=="filled" and not match.get("executions") and not match.get("filled_asset_quantity"):
                continue
            if status in FINAL:row["status"]=status
        self._save(doc)
        return len(self.pending())==0
