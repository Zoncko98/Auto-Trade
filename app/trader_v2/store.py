"""Transactional append-only V2 journal. Separate from all existing V1 ledgers.

SQLite WAL + synchronous FULL, BEGIN IMMEDIATE single-writer serialization;
no deletion/replacement of legacy order data. Unknown outcomes never replay POSTs.
"""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime,timezone
from pathlib import Path
import hashlib,json,os,sqlite3
from .models import OrderIntent,OrderState,RiskDecision,TERMINAL,utc

_TRANSITIONS={
    OrderState.PROPOSED:{OrderState.RISK_APPROVED},
    OrderState.RISK_APPROVED:{OrderState.INTENT_PERSISTED},
    OrderState.INTENT_PERSISTED:{OrderState.SUBMITTING,OrderState.REJECTED},
    OrderState.SUBMITTING:{OrderState.BROKER_ACCEPTED,OrderState.UNKNOWN_REQUIRES_RECONCILIATION,OrderState.REJECTED},
    OrderState.BROKER_ACCEPTED:{OrderState.PARTIALLY_FILLED,OrderState.FILLED,OrderState.CANCELED,OrderState.UNKNOWN_REQUIRES_RECONCILIATION,OrderState.REJECTED},
    OrderState.PARTIALLY_FILLED:{OrderState.PARTIALLY_FILLED,OrderState.FILLED,OrderState.CANCELED,OrderState.UNKNOWN_REQUIRES_RECONCILIATION},
    OrderState.UNKNOWN_REQUIRES_RECONCILIATION:{OrderState.BROKER_ACCEPTED,OrderState.FILLED,OrderState.CANCELED,OrderState.REJECTED},
}

class IntentConflict(ValueError):pass
class IllegalTransition(ValueError):pass

def _encode(intent:OrderIntent)->str:
    return json.dumps({
        "key":intent.key,"account_id":intent.account_id,"strategy":intent.strategy,
        "symbol":intent.symbol,"asset_class":intent.asset_class.value,
        "side":intent.side.value,"quantity":str(intent.quantity),
        "limit_price":str(intent.limit_price),"proposed_at":intent.proposed_at.isoformat()
    },sort_keys=True,separators=(",",":"),allow_nan=False)

class EventStore:
    """Every operation opens an independent SQLite connection and transaction."""
    def __init__(self,path):
        self.path=Path(path)
        self.path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        if self.path.parent.stat().st_mode & 0o007:
            raise PermissionError("V2 journal directory is world-accessible")
        if not self.path.exists():
            try:
                fd=os.open(self.path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
                os.close(fd)
            except FileExistsError:pass
        if self.path.stat().st_mode & 0o077:
            raise PermissionError("Unsafe V2 journal file permissions")
        self._initialize()

    def _connect(self):
        connection=sqlite3.connect(str(self.path),timeout=10,isolation_level=None)
        connection.row_factory=sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self):
        with self._connect() as db:
            mode=db.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            if mode.lower()!="wal":raise RuntimeError("Durable WAL mode unavailable")
            db.execute("PRAGMA synchronous=FULL")
            db.executescript("""
              CREATE TABLE IF NOT EXISTS intents(
                key TEXT PRIMARY KEY, account_id TEXT NOT NULL,
                fingerprint TEXT NOT NULL, document TEXT NOT NULL,
                state TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS events(
                seq INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT NOT NULL,
                account_id TEXT NOT NULL, state TEXT NOT NULL,
                evidence TEXT NOT NULL, recorded_at TEXT NOT NULL,
                FOREIGN KEY(key) REFERENCES intents(key));
              CREATE INDEX IF NOT EXISTS events_by_account
                ON events(account_id,seq);
              CREATE TABLE IF NOT EXISTS reviews(
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL, account_id TEXT NOT NULL, code TEXT NOT NULL,
                reason TEXT NOT NULL, recorded_at TEXT NOT NULL);
              CREATE INDEX IF NOT EXISTS reviews_by_account
                ON reviews(account_id,seq);
            """)

    @contextmanager
    def _write(self):
        conn=self._connect()
        try:
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    @staticmethod
    def _now():return datetime.now(timezone.utc).isoformat()

    def _event(self,db,key,account_id,state,evidence):
        if not isinstance(evidence,dict) or len(json.dumps(evidence,allow_nan=False))>3500:
            raise ValueError("Invalid or oversized event metadata")
        db.execute("INSERT INTO events(key,account_id,state,evidence,recorded_at) VALUES(?,?,?,?,?)",
            (key,account_id,state.value,json.dumps(evidence,sort_keys=True,allow_nan=False),self._now()))

    def prepare(self,intent:OrderIntent,decision:RiskDecision)->dict:
        """Idempotently persist PROPOSED -> RISK_APPROVED -> INTENT_PERSISTED.

        No broker call occurs here. A duplicate key with different terms is rejected.
        """
        if not isinstance(intent,OrderIntent) or not isinstance(decision,RiskDecision) or decision.code!="PASS":
            raise ValueError("A complete, approved risk decision is required")
        if intent.quantity!=decision.quantity or intent.limit_price!=decision.limit_price:
            raise ValueError("Approved risk quantity/price differ from intent")
        raw=_encode(intent)
        fingerprint=hashlib.sha256(raw.encode()).hexdigest()
        with self._write() as db:
            row=db.execute("SELECT * FROM intents WHERE key=?",(intent.key,)).fetchone()
            if row is not None:
                if row["fingerprint"]!=fingerprint or row["document"]!=raw:
                    raise IntentConflict("Conflicting idempotency key")
                return dict(row)
            competing=db.execute(
                """SELECT key FROM intents WHERE account_id=?
                   AND state NOT IN ('FILLED','CANCELED','REJECTED')
                   LIMIT 1""",(intent.account_id,)).fetchone()
            if competing is not None:
                raise IntentConflict("Account has an unresolved order intent")
            now=self._now()
            db.execute("INSERT INTO intents VALUES(?,?,?,?,?,?,?)",
                       (intent.key,intent.account_id,fingerprint,raw,
                        OrderState.PROPOSED.value,now,now))
            self._event(db,intent.key,intent.account_id,OrderState.PROPOSED,{"strategy":intent.strategy})
            self._event(db,intent.key,intent.account_id,OrderState.RISK_APPROVED,
                        {"reason":decision.reason,"effective_headroom":str(decision.effective_headroom)})
            self._event(db,intent.key,intent.account_id,OrderState.INTENT_PERSISTED,{})
            db.execute("UPDATE intents SET state=?,updated_at=? WHERE key=?",
                        (OrderState.INTENT_PERSISTED.value,now,intent.key))
            return dict(db.execute("SELECT * FROM intents WHERE key=?",(intent.key,)).fetchone())

    def transition(self,key,target:OrderState,*,evidence=None)->dict:
        if not isinstance(target,OrderState):raise ValueError("Invalid transition state")
        with self._write() as db:
            row=db.execute("SELECT * FROM intents WHERE key=?",(key,)).fetchone()
            if row is None:raise KeyError("Unknown order intent")
            old=OrderState(row["state"])
            if target not in _TRANSITIONS.get(old,set()):
                raise IllegalTransition(f"{old.value} -> {target.value} not permitted")
            self._event(db,key,row["account_id"],target,evidence or {})
            db.execute("UPDATE intents SET state=?,updated_at=? WHERE key=?",
                       (target.value,self._now(),key))
            return dict(db.execute("SELECT * FROM intents WHERE key=?",(key,)).fetchone())

    def get(self,key):
        with self._connect() as db:
            row=db.execute("SELECT * FROM intents WHERE key=?",(key,)).fetchone()
            return dict(row) if row else None

    def events(self,key):
        with self._connect() as db:
            rows=db.execute("SELECT seq,state,evidence,recorded_at FROM events WHERE key=? ORDER BY seq",(key,)).fetchall()
            return [{**dict(row),"evidence":json.loads(row["evidence"])} for row in rows]

    def review(self,key,account_id,code,reason):
        if not isinstance(code,str) or len(code)>50 or not isinstance(reason,str) or len(reason)>180:
            raise ValueError("Invalid decision review")
        with self._write() as db:
            db.execute("INSERT INTO reviews(key,account_id,code,reason,recorded_at) VALUES(?,?,?,?,?)",
                       (key,account_id,code,reason,self._now()))

    def pending(self,account_id=None):
        sql="SELECT * FROM intents WHERE state NOT IN (?,?,?)"
        params=[x.value for x in TERMINAL]
        if account_id:
            sql+=" AND account_id=?";params.append(account_id)
        sql+=" ORDER BY updated_at"
        with self._connect() as db:
            return [dict(row) for row in db.execute(sql,params).fetchall()]

    def summary(self):
        with self._connect() as db:
            states={row["state"]:row["n"] for row in db.execute(
                "SELECT state,COUNT(*) AS n FROM intents GROUP BY state")}
            events=db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            reviews=db.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
            return {"intents":sum(states.values()),"events":events,"reviews":reviews,
                    "states":states,"unresolved":sum(v for k,v in states.items()
                    if OrderState(k) not in TERMINAL),"schema":"trader-v2-1"}
