"""Account-specific V2 live fill and position projection from durable receipts.

Read-only. A broker order ACK is not inventory; only reconciled fills create
lots. Cumulative partial fills are counted once, not once per poll. All pending
or uncertain histories block migration/oversell. No API orders.
"""
from __future__ import annotations
from datetime import datetime,timezone
from decimal import Decimal,InvalidOperation
from hashlib import sha256
from pathlib import Path
import json,sqlite3,stat
from .models import AssetClass,OrderSide,OrderState,amount,valid_id

RECEIPT_STATES=frozenset((
    "PARTIALLY_FILLED","FILLED","CANCELED","REJECTED"
))
TERMINAL=frozenset(("FILLED","CANCELED","REJECTED"))

class PortfolioEvidenceError(ValueError):
    def __init__(self,code):
        self.code=code
        super().__init__(code)

def _money(v,label):
    try:return amount(v,label)
    except (ValueError,TypeError):
        raise PortfolioEvidenceError("V2_FILL_ECONOMICS_INVALID") from None

def _read_rows(path,account):
    if path.is_symlink():
        raise PortfolioEvidenceError("V2_JOURNAL_SYMLINK")
    try:
        info=path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_mode&0o077 or info.st_size>40_000_000:
            raise ValueError
        with sqlite3.connect("file:"+str(path.absolute())+"?mode=ro",uri=True,timeout=3) as db:
            db.execute("PRAGMA query_only=ON")
            rows=db.execute("SELECT key,account_id,fingerprint,document,state,created_at "
                "FROM intents WHERE account_id=? ORDER BY created_at,key LIMIT 2001",(account,)).fetchall()
            if len(rows)>2000:
                raise PortfolioEvidenceError("V2_JOURNAL_TOO_MANY_INTENTS")
            events=db.execute("SELECT key,seq,state,evidence,recorded_at "
                "FROM events WHERE account_id=? ORDER BY seq LIMIT 8001",(account,)).fetchall()
            if len(events)>8000:
                raise PortfolioEvidenceError("V2_JOURNAL_TOO_MANY_EVENTS")
            return rows,events
    except PortfolioEvidenceError:
        raise
    except (OSError,ValueError,sqlite3.Error):
        raise PortfolioEvidenceError("V2_JOURNAL_UNREADABLE") from None

def reconstruct(state_dir,account):
    valid_id(account)
    path=Path(state_dir)/"v2"/"events.sqlite3"
    rows,raw_events=_read_rows(path,account)
    events={}
    for key,seq,state,evidence,recorded in raw_events:
        try:
            item=json.loads(evidence)
        except (TypeError,ValueError):
            raise PortfolioEvidenceError("V2_EVENT_EVIDENCE_UNREADABLE") from None
        if not isinstance(item,dict):
            raise PortfolioEvidenceError("V2_EVENT_EVIDENCE_UNREADABLE")
        events.setdefault(key,[]).append((state,item,recorded))
    positions={}
    lots=[]
    uncertain=[]
    total_buys=0
    total_sells=0
    realized=Decimal("0")
    realized_by_day={}
    for key,account_id,hashval,raw,state,created in rows:
        try:
            document=json.loads(raw)
            if (not isinstance(document,dict) or
                sha256(raw.encode()).hexdigest()!=hashval or
                document.get("key")!=key or document.get("account_id")!=account or
                document.get("side") not in ("BUY","SELL") or
                document.get("asset_class") not in ("CRYPTO","STOCK")):
                raise ValueError
            symbol=document["symbol"]
            qty=_money(document["quantity"],"intent quantity")
            if qty<=0:raise ValueError
            order=events.get(key,[])
            if not order or order[0][0]!="PROPOSED":
                raise ValueError
            latest=Decimal("0")
            price=Decimal("0")
            fees=Decimal("0")
            last_receipt_at=None
            for event_state,detail,at in order:
                if event_state in RECEIPT_STATES and "filled_quantity" in detail:
                    filled=_money(detail["filled_quantity"],"cumulative fill")
                    next_price=_money(detail.get("average_price"),"fill average price")
                    next_fee=_money(detail.get("fees"),"fill cumulative fee")
                    if filled<latest or filled>qty or (
                        filled>0 and next_price==0) or next_fee<fees:
                        raise ValueError
                    latest,price,fees=filled,next_price,next_fee
                    last_receipt_at=at
            if state not in TERMINAL:
                uncertain.append(key)
            if state=="FILLED" and latest!=qty:
                raise ValueError
            if latest:
                lots.append((last_receipt_at or created,created,key,symbol,document["side"],
                             document["asset_class"],latest,price,fees))
        except (ValueError,TypeError,KeyError,IndexError,InvalidOperation):
            raise PortfolioEvidenceError("V2_ORIGINAL_ORDER_OR_RECEIPT_UNVERIFIED") from None
    if set(events).difference(row[0] for row in rows):
        raise PortfolioEvidenceError("V2_ORPHAN_OR_FOREIGN_ORDER_EVENT")
    for at,created,key,symbol,side,asset,qty,price,fees in sorted(lots):
        # The timestamp is the durable local confirmation of the signed
        # receipt, NOT necessarily the broker's original execution time.
        # It is conservative for minimum-hold timing; daily P&L is explicitly
        # categorized by reconciliation day, not inferred broker-fill day.
        try:
            closed_at=datetime.fromisoformat(at.replace("Z","+00:00"))
            if closed_at.tzinfo is None:
                raise ValueError
            closed_at=closed_at.astimezone(timezone.utc)
        except (ValueError,TypeError,AttributeError):
            raise PortfolioEvidenceError("V2_SIGNED_FILL_EVENT_TIME_UNVERIFIED") from None
        identity=(symbol,asset)
        row=positions.setdefault(identity,{"quantity":Decimal("0"),
                                            "cost":Decimal("0"),"opened_at":None})
        if side=="BUY":
            total_buys+=1
            if row["quantity"]==0:
                row["opened_at"]=closed_at
            row["cost"]+=qty*price+fees
            row["quantity"]+=qty
        else:
            total_sells+=1
            if qty>row["quantity"]:
                raise PortfolioEvidenceError("V2_SELL_EXCEEDS_VERIFIED_INVENTORY")
            unit_cost=row["cost"]/row["quantity"]
            allocated=unit_cost*qty
            gain=qty*price-allocated-fees
            realized+=gain
            day=closed_at.date().isoformat()
            realized_by_day[day]=realized_by_day.get(day,Decimal("0"))+gain
            row["quantity"]-=qty
            row["cost"]-=allocated
            if row["quantity"]==0:
                row["cost"]=Decimal("0")
                row["opened_at"]=None
    # Do not disclose account identifier or arbitrary original order keys.
    inventory={sym:{"asset_class":asset,"quantity":str(row["quantity"]),
                    "cost_basis":str(row["cost"]/row["quantity"]),
                    "opened_at":row["opened_at"].isoformat()}
        for (sym,asset),row in positions.items() if row["quantity"]>0}
    return {"state":"RECONCILIATION_REQUIRED" if uncertain else "RECONCILED",
            "account_identity_verified":False,
      "journal_account_scoped":True,
            "reconciled_lots":len(lots),
            "buy_fills":total_buys,"sell_fills":total_sells,
            "unresolved_intents":len(uncertain),
            "realized_net_usd":str(realized),
            "realized_net_by_reconciled_utc_day":{d:str(v) for d,v in sorted(realized_by_day.items())},
            "verified_v2_inventory":inventory,
            "live_order_authority":False}
