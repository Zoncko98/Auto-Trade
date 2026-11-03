"""SQLite-backed, broker-specific order intents and reconciliation.

An intent is fsynced before any broker write. Unknown or partial outcomes retain
the lock across crashes/restarts. No order is re-sent with a new identifier.
"""
import os,re,sqlite3
from contextlib import contextmanager
from datetime import datetime,timezone
from decimal import Decimal,InvalidOperation
from pathlib import Path
from webull_broker import positive

FINAL=("FILLED","CANCELLED","FAILED")
class JournalBlocked(RuntimeError):pass

def _utc():return datetime.now(timezone.utc).isoformat()
def _decimal(v):
    try:d=Decimal(str(v))
    except (InvalidOperation,ValueError,TypeError):raise JournalBlocked("Invalid broker fill number") from None
    if not d.is_finite() or d<0:raise JournalBlocked("Invalid broker fill number")
    return d

class WebullJournal:
    def __init__(self,state):
        self.folder=Path(state)/"webull"
        self.folder.mkdir(parents=True,exist_ok=True,mode=0o700)
        if self.folder.is_symlink() or not self.folder.is_dir():
            raise JournalBlocked("Unsafe Webull state directory")
        if self.folder.stat().st_mode & 0o077:
            # Older Webull integration created /state/webull with 0755.
            # Tighten the existing directory, never relax access.
            os.chmod(self.folder,0o700)
        if self.folder.stat().st_mode & 0o077:
            raise JournalBlocked("Unsafe journal directory permissions")
        self.path=self.folder/"orders.sqlite3"
        # Creating via sqlite uses the process umask, enforce mode on every open.
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS orders(
                client_id TEXT PRIMARY KEY, account TEXT NOT NULL, symbol TEXT NOT NULL,
                asset TEXT NOT NULL, side TEXT NOT NULL,
                quantity TEXT NOT NULL, limit_price TEXT NOT NULL,
                status TEXT NOT NULL, created_at TEXT NOT NULL,
                checked_at TEXT, filled_qty TEXT, filled_price TEXT, fee TEXT, fill_at TEXT,
                broker_id TEXT, broker_status TEXT, error_category TEXT,
                rationale TEXT NOT NULL)""")
    @contextmanager
    def _db(self):
        db=sqlite3.connect(self.path,timeout=10,isolation_level=None)
        os.chmod(self.path,0o600)
        try:
            db.execute("PRAGMA busy_timeout=10000")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise
        finally:db.close()
    @staticmethod
    def _row(row):
        fields=("client_id","account","symbol","asset","side","quantity",
               "limit_price","status","created_at","checked_at","filled_qty",
               "filled_price","fee","fill_at","broker_id","broker_status","error_category","rationale")
        return dict(zip(fields,row))
    def recent(self,limit=50):
        with self._db() as db:
            rows=db.execute("SELECT * FROM orders ORDER BY created_at DESC LIMIT ?",(min(max(int(limit),1),100),)).fetchall()
        return [self._row(r) for r in rows]
    def pending(self,account):
        with self._db() as db:
            rows=db.execute("SELECT * FROM orders WHERE account=? AND status NOT IN ('FILLED','CANCELLED','FAILED') ORDER BY created_at",(account,)).fetchall()
        return [self._row(r) for r in rows]
    def new_intent(self,account,client_id,symbol,asset,side,qty,limit_price,rationale):
        if not isinstance(account,str) or not account or len(account)>80:raise JournalBlocked("Invalid account")
        if not re.fullmatch("[a-f0-9]{32}",client_id):raise JournalBlocked("Invalid order id")
        if asset not in ("EQUITY","CRYPTO") or side not in ("BUY","SELL"):
            raise JournalBlocked("Unsupported order")
        positive(qty);positive(limit_price)
        with self._db() as db:
            if db.execute("SELECT 1 FROM orders WHERE account=? AND status NOT IN ('FILLED','CANCELLED','FAILED') LIMIT 1",
                          (account,)).fetchone():
                raise JournalBlocked("Unresolved Webull order prevents duplicate submission")
            db.execute("INSERT INTO orders(client_id,account,symbol,asset,side,quantity,limit_price,status,created_at,rationale) VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (client_id,account,symbol,asset,side,str(qty),str(limit_price),
                        "INTENT_UNCONFIRMED",_utc(),str(rationale)[:280]))
    def acknowledged(self,client_id,reply):
        # Broker response is only an acknowledgment, not a fill.
        with self._db() as db:
            if not db.execute("SELECT 1 FROM orders WHERE client_id=?",(client_id,)).fetchone():
                raise JournalBlocked("Unknown order intent")
            db.execute("UPDATE orders SET status='SUBMITTED_UNCONFIRMED',checked_at=? WHERE client_id=? AND status='INTENT_UNCONFIRMED'",
                       (_utc(),client_id))
    @staticmethod
    def _detail(payload,client_id):
        # Webull v3 returns a combo with suborders; require unique requested order.
        if isinstance(payload,dict) and isinstance(payload.get("orders"),list):
            rows=payload["orders"]
        elif isinstance(payload,dict):
            rows=[payload]
        else:raise JournalBlocked("Broker order detail shape not supported")
        matches=[r for r in rows if isinstance(r,dict) and r.get("client_order_id")==client_id]
        if len(matches)!=1:raise JournalBlocked("Order detail doesn't match client order ID")
        return matches[0]
    def reconcile(self,account,broker):
        rows=self.pending(account)
        outcomes=[]
        for row in rows:
            try:
                item=self._detail(broker.order_detail(account,row["client_id"]),row["client_id"])
                state=item.get("status")
                if not isinstance(state,str):raise JournalBlocked("Missing broker order status")
                state=state.upper()
                if state not in ("PENDING","SUBMITTED","PARTIAL_FILLED","FILLED","CANCELLED","FAILED"):
                    raise JournalBlocked("Unrecognized broker order state")
                fill_qty=_decimal(item.get("filled_quantity") or "0")
                limit_qty=_decimal(row["quantity"])
                if fill_qty>limit_qty:raise JournalBlocked("Broker fill exceeds intent")
                final=state in FINAL
                price=_decimal(item.get("filled_price") or "0")
                if fill_qty>0 and price<=0:raise JournalBlocked("Broker fill price unavailable")
                fee=item.get("fee_charged")
                fee_d=_decimal(fee) if fee is not None else None
                when=item.get("filled_time_at")
                if when is not None:
                    try:
                        stamp=datetime.fromisoformat(when.replace("Z","+00:00"))
                        if stamp.tzinfo is None:raise ValueError()
                    except (ValueError,TypeError,AttributeError):
                        raise JournalBlocked("Invalid broker fill timestamp") from None
                if fill_qty>0 and not when:raise JournalBlocked("Fill timestamp missing")
                # Partial fills on cancelled/failed orders are not silently terminal.
                if final and state=="FILLED" and fill_qty!=limit_qty:
                    raise JournalBlocked("Filled order quantity mismatch")
                status=("PARTIAL_TERMINAL" if final and fill_qty>0 and state!="FILLED"
                        else state if final else state)
                broker_id=item.get("order_id")
                with self._db() as db:
                    db.execute("""UPDATE orders SET status=?, broker_status=?, broker_id=?,
                       checked_at=?,filled_qty=?,filled_price=?,fee=?,fill_at=? WHERE client_id=? AND account=?""",
                      (status,state,str(broker_id)[:80] if broker_id is not None else None,
                       _utc(),str(fill_qty),str(price) if price>0 else None,
                       str(fee_d) if fee_d is not None else None,
                       when,row["client_id"],account))
                outcomes.append({"client_id":row["client_id"],"state":status})
            except Exception as exc:
                # A failed lookup is not a broker cancellation; retain the intent.
                outcomes.append({"client_id":row["client_id"],"state":"RECONCILIATION_UNAVAILABLE",
                                 "reason":type(exc).__name__})
        return outcomes
    def positions(self,account):
        # Only fully broker-confirmed fills establish bot-owned positions.
        with self._db() as db:
            rows=db.execute("""SELECT symbol,asset,side,filled_qty,filled_price,fee,fill_at
                FROM orders WHERE account=? AND status='FILLED'
                ORDER BY created_at,client_id""",(account,)).fetchall()
        holdings={}
        realized=Decimal("0")
        for sym,asset,side,q,p,f,at in rows:
            qty=_decimal(q); price=_decimal(p); fee=_decimal(f) if f is not None else Decimal("0")
            entry=holdings.setdefault((sym,asset),{"quantity":Decimal("0"),"cost":Decimal("0"),"opened_at":None})
            if side=="BUY":
                if entry["quantity"]==0:entry["opened_at"]=at
                entry["quantity"]+=qty;entry["cost"]+=qty*price+fee
            else:
                if qty>entry["quantity"]:raise JournalBlocked("Bot sell exceeds verified inventory")
                unit=entry["cost"]/entry["quantity"] if entry["quantity"] else Decimal("0")
                realized+=(price-unit)*qty-fee
                entry["quantity"]-=qty;entry["cost"]-=unit*qty
                if entry["quantity"]==0:entry["opened_at"]=None;entry["cost"]=Decimal("0")
        return {sym:{"asset":asset,"quantity":str(row["quantity"]),
                     "cost_basis":str(row["cost"]/row["quantity"]),"opened_at":row["opened_at"]}
                for (sym,asset),row in holdings.items() if row["quantity"]>0},str(realized)
