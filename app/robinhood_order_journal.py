"""Durable account-scoped Robinhood order journal and verified cost basis."""
import json,os,tempfile
from datetime import datetime,timezone
from uuid import uuid4
from decimal import Decimal,InvalidOperation
from pathlib import Path

FINAL={"filled","canceled","cancelled","failed","rejected","expired","externally_reconciled"}

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
            "status":"intent_unconfirmed","created_at":datetime.now(timezone.utc).isoformat()})
        self._save(doc)

    def mark_submission_ack(self,client_id,response):
        doc=self.load()
        rows=[row for row in doc["orders"] if row.get("client_order_id")==client_id]
        if len(rows)!=1:raise UnreconciledOrder("Order intent not uniquely found")
        row=rows[0]
        if isinstance(response,dict):
            if response.get("id"):row["broker_order_id"]=str(response["id"])
            if response.get("state"):row["broker_state"]=str(response["state"])
            if response.get("created_at") and not row.get("created_at"):
                row["created_at"]=response["created_at"]
        row["status"]="submitted_unconfirmed"
        self._save(doc)

    def mark_submission_rejected(self,client_id,reason):
        doc=self.load()
        rows=[row for row in doc["orders"] if row.get("client_order_id")==client_id]
        if len(rows)!=1:raise UnreconciledOrder("Order intent not uniquely found")
        row=rows[0]
        row["status"]="rejected"
        row["submission_error"]=str(reason)[:160]
        row["resolved_at"]=datetime.now(timezone.utc).isoformat()
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

    def _recompute_realized(self,doc,account=None):
        positions={}
        for row in doc["orders"]:
            if account is not None and row.get("account")!=account:
                continue
            row.pop("realized_pnl_usd",None)
            if row.get("side")=="external_reduction" and row.get("status")=="externally_reconciled":
                qty=_dec(row.get("quantity"),positive=True)
                symbol=row.get("symbol")
                state=positions.get(symbol)
                if qty is None or state is None or qty>state["quantity"]:
                    if state is not None:state["verified"]=False
                    continue
                unit=state["cost"]/state["quantity"]
                state["quantity"]-=qty
                state["cost"]-=unit*qty
                if state["quantity"]==0:
                    state["cost"]=Decimal("0")
                    state["opened_at"]=None
                continue
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
        now=datetime.now(timezone.utc)
        for row in doc["orders"]:
            if row["account"]!=account:continue
            match=by_id.get(row["client_order_id"])
            if match is None:
                if row.get("status") not in FINAL:
                    row["reconcile_miss_count"]=int(row.get("reconcile_miss_count") or 0)+1
                    row.setdefault("first_reconcile_miss_at",now.isoformat())
                    row["last_reconcile_check_at"]=now.isoformat()
                    reference=_timestamp(row.get("created_at")) or _timestamp(row.get("first_reconcile_miss_at"))
                    age=(now-reference.astimezone(timezone.utc)).total_seconds() if reference else None
                    # The full broker order list is authoritative. Require both
                    # repeated successful misses and a substantial grace period
                    # before resolving a legacy local intent that has no broker record.
                    if age is not None and age>=600 and row["reconcile_miss_count"]>=10:
                        row["status"]="rejected"
                        row["submission_error"]="No Robinhood order found after 10+ successful reconciliation checks over 10+ minutes"
                        row["resolved_at"]=now.isoformat()
                continue
            row["reconcile_miss_count"]=0
            row["last_reconcile_check_at"]=now.isoformat()
            if match.get("id"):row["broker_order_id"]=str(match["id"])
            status=str(match.get("state",match.get("status",""))).lower()
            if status:row["broker_state"]=status
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

    def reconcile_external_sells(self,account,broker_orders,broker_holdings):
        """Correct stale bot inventory only when *both* broker holdings and
        broker-confirmed external sell fills prove the reduction.

        This records an external adjustment without pretending that Auto Trader
        executed the sale, or attributing an unknown realized P/L to the bot.
        """
        if not isinstance(account,str) or not account:
            raise UnreconciledOrder("External reconciliation account invalid")
        if not isinstance(broker_orders,list) or not isinstance(broker_holdings,list):
            raise UnreconciledOrder("Complete broker holdings and orders required")
        if self.pending():
            return {"status":"PENDING_BOT_ORDER","adjustments":[]}
        if any(isinstance(o,dict) and str(o.get("state","")).lower() in
               ("open","pending","partially_filled","queued") for o in broker_orders):
            return {"status":"PENDING_BROKER_ORDER","adjustments":[]}
        totals={}
        for item in broker_holdings:
            if not isinstance(item,dict):
                raise UnreconciledOrder("Broker holdings response invalid")
            asset=item.get("asset_code")
            qty=_dec(item.get("total_quantity"))
            if not isinstance(asset,str) or not asset or qty is None or asset in totals:
                raise UnreconciledOrder("Broker holdings missing unique asset or quantity")
            totals[asset+"-USD"]=qty

        doc=self.load()
        bot_orders=[r for r in doc["orders"] if r.get("account")==account
                    and r.get("side") in ("buy","sell")]
        owned_client_ids={r.get("client_order_id") for r in bot_orders}
        previously_imported=set()
        for r in doc["orders"]:
            if r.get("side")=="external_reduction" and r.get("account")==account:
                previously_imported.update(r.get("external_broker_order_ids") or [])
        bot_positions=self.positions(account)
        if not bot_positions:
            return {"status":"NO_BOT_POSITIONS","adjustments":[]}
        pending_adjustments=[]
        unmatched=[]
        for symbol,pos in bot_positions.items():
            held=pos["quantity"]
            broker_qty=totals.get(symbol,Decimal("0"))
            difference=held-broker_qty
            if difference<=max(Decimal("0.00000001"),held*Decimal("0.0000000001")):
                continue
            latest_fill=None
            for row in bot_orders:
                if row.get("symbol")!=symbol or row.get("side")!="buy" or row.get("status")!="filled":
                    continue
                stamp=_timestamp(row.get("filled_at"))
                if stamp is None:
                    # Without a verified buy time, chronological external-sell
                    # attribution is unsafe.
                    latest_fill=None
                    break
                if latest_fill is None or stamp>latest_fill:
                    latest_fill=stamp
            if latest_fill is None:
                unmatched.append(symbol)
                continue
            eligible=[]
            for row in broker_orders:
                if not isinstance(row,dict) or row.get("symbol")!=symbol:continue
                if str(row.get("side","")).lower()!="sell" or str(row.get("state","")).lower()!="filled":
                    continue
                broker_id=row.get("id")
                if not isinstance(broker_id,str) or not broker_id or broker_id in previously_imported:
                    continue
                if row.get("client_order_id") in owned_client_ids:continue
                fill_qty=_dec(row.get("filled_asset_quantity"),positive=True)
                when=_timestamp(row.get("updated_at")) or _timestamp(row.get("created_at"))
                if fill_qty is None or when is None or when<=latest_fill:continue
                eligible.append((broker_id,fill_qty,when))
            eligible_qty=sum((q for _,q,_ in eligible),Decimal("0"))
            if eligible_qty<difference:
                unmatched.append(symbol)
                continue
            evidence_ids=[broker_id for broker_id,_,_ in eligible]
            external_sell_at=max(when for _,_,when in eligible)
            pending_adjustments.append((symbol,difference,broker_qty,evidence_ids,external_sell_at))
        if not pending_adjustments:
            return {"status":"BROKER_HOLDINGS_MISMATCH" if unmatched else "NO_ADJUSTMENT_NEEDED",
                    "adjustments":[],"unmatched":unmatched}
        for symbol,quantity,broker_qty,ids,external_sell_at in pending_adjustments:
            doc["orders"].append({
                "account":account,
                "client_order_id":"external-reconcile-"+str(uuid4()),
                "symbol":symbol,"side":"external_reduction",
                "status":"externally_reconciled",
                "quantity":str(quantity),
                "broker_remaining_quantity":str(broker_qty),
                "external_broker_order_ids":ids,
                "source":"broker_verified_external_sale",
                "realized_pnl_usd":None,
                "filled_at":external_sell_at.isoformat(),
                "created_at":datetime.now(timezone.utc).isoformat(),
                "note":"Manual/external sale corroborated by broker holdings; not a bot order"})
        self._save(doc)
        return {"status":"EXTERNAL_SALE_RECONCILED","adjustments":[
            {"symbol":sym,"quantity":str(qty),"broker_remaining_quantity":str(remaining)}
            for sym,qty,remaining,_,_ in pending_adjustments],
                "unmatched":unmatched}

    def positions(self,account=None):
        doc=self.load()
        states=self._recompute_realized(doc,account=account)
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
               if row.get("symbol")==symbol and
               ((row.get("side")=="sell" and row.get("status")=="filled") or
                (row.get("side")=="external_reduction" and row.get("status")=="externally_reconciled"))]
        times=[t for t in times if t is not None]
        return max(times) if times else None
