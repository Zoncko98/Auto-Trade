"""Durable 24h/7d scorecards for genuine V2 public crypto paper scans.

This independent observation ledger is NOT an order journal, and all returns
are synthetic, marked-to-market virtual-account results. No broker imports,
credential reads or live order authority.
"""
from __future__ import annotations
from datetime import datetime,timezone,timedelta
from decimal import Decimal,InvalidOperation
from pathlib import Path
import os,re,sqlite3,stat

SYMBOLS=("BTCUSD","ETHUSD")
STATES=("PASS","VETO","UNAVAILABLE","NOT_CONFIGURED","NOT_INVOKED")
FEE_STATES=("NOT_INVOKED","EXIT_NOT_GATED","INSUFFICIENT_HISTORY",
    "EVIDENCE_UNAVAILABLE","SHADOW_PASS_PAST_RESISTANCE_ROOM",
    "SHADOW_REJECT_REWARD_AFTER_FEES","SHADOW_REJECT_SPREAD")
DB_NAME="paper_scan_history.sqlite3"

def _stamp(value):
    if not isinstance(value,str) or len(value)>45:raise ValueError("INVALID_SCAN_TIME")
    dt=datetime.fromisoformat(value.replace("Z","+00:00"))
    if dt.tzinfo is None:raise ValueError("UNVERIFIED_SCAN_TIME")
    return dt.astimezone(timezone.utc)

def _money(value):
    if value is None:return None
    try:x=Decimal(str(value))
    except (ValueError,TypeError,InvalidOperation):raise ValueError("INVALID_PAPER_VALUE") from None
    if not x.is_finite() or x<0 or x>1_000_000_000:
        raise ValueError("INVALID_PAPER_VALUE")
    return str(x)

def _normalize(report):
    if (not isinstance(report,dict) or report.get("symbol") not in SYMBOLS
        or report.get("simulated_only") is not True
        or report.get("live_orders_submitted")!=0):
        raise ValueError("NOT_A_SIMULATED_SCAN")
    state=report.get("scan_state")
    if not isinstance(state,str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}",state):
        raise ValueError("INVALID_SCAN_STATE")
    ai=report.get("ai_shadow")
    ai_state=ai.get("state","NOT_INVOKED") if isinstance(ai,dict) else "NOT_INVOKED"
    if ai_state not in STATES:ai_state="UNAVAILABLE"
    side=report.get("signal")
    if side not in (None,"BUY","SELL"):raise ValueError("INVALID_SCAN_SIGNAL")
    at=_stamp(report["at"])
    minute=int(at.timestamp())//60*60
    priority=5 if state=="FILLED" else 3 if side else 2 if state=="NO_SIGNAL" else 1
    reason=str(report.get("reason",""))[:80]
    fee=report.get("fee_shadow")
    fee_state="NOT_INVOKED"
    if isinstance(fee,dict):
        candidate=fee.get("state")
        if (candidate in FEE_STATES and fee.get("changed_execution") is False
                and fee.get("live_order_authorized") is False):
            fee_state=candidate
        elif candidate not in (None,"NOT_INVOKED"):
            fee_state="EVIDENCE_UNAVAILABLE"
    if fee_state.startswith("SHADOW_") and side!="BUY":
        fee_state="EVIDENCE_UNAVAILABLE"
    return (report["symbol"],minute,at.isoformat(),state,reason,side,
            ai_state,priority,_money(report.get("virtual_equity")),
            _money(report.get("virtual_cash")),fee_state)

def capture_scan(directory,report):
    values=_normalize(report)
    base=Path(directory)
    if base.is_symlink() or not base.is_dir() or base.stat().st_mode & 0o077:
        raise PermissionError("UNSAFE_PAPER_METRICS_DIRECTORY")
    path=base/DB_NAME
    if path.is_symlink():raise PermissionError("UNSAFE_PAPER_METRICS_DATABASE")
    if not path.exists():
        try:
            fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            os.close(fd)
        except FileExistsError:pass
    if path.stat().st_mode&0o077:raise PermissionError("UNSAFE_PAPER_METRICS_DATABASE")
    with sqlite3.connect(str(path),timeout=5) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("""CREATE TABLE IF NOT EXISTS paper_scans(
            symbol TEXT NOT NULL, minute INTEGER NOT NULL, scanned_at TEXT NOT NULL,
            state TEXT NOT NULL, reason TEXT NOT NULL, signal TEXT,
            ai_state TEXT NOT NULL, priority INTEGER NOT NULL,
            equity TEXT, cash TEXT, attempts INTEGER NOT NULL DEFAULT 1,
            fee_shadow_state TEXT,
            PRIMARY KEY(symbol,minute))""")
        # Existing V2 30-day journals retain their original rows and scans.
        # Add only the new diagnostic column, never rewrite order journals.
        columns={row[1] for row in db.execute("PRAGMA table_info(paper_scans)")}
        if "fee_shadow_state" not in columns:
            db.execute("ALTER TABLE paper_scans ADD COLUMN fee_shadow_state TEXT")
        db.execute("""INSERT INTO paper_scans
            (symbol,minute,scanned_at,state,reason,signal,ai_state,priority,equity,cash,fee_shadow_state)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(symbol,minute) DO UPDATE SET
              attempts=paper_scans.attempts+1,
              scanned_at=excluded.scanned_at,
              state=CASE WHEN excluded.priority>=paper_scans.priority
                    THEN excluded.state ELSE paper_scans.state END,
              reason=CASE WHEN excluded.priority>=paper_scans.priority
                    THEN excluded.reason ELSE paper_scans.reason END,
              signal=COALESCE(paper_scans.signal,excluded.signal),
              ai_state=CASE WHEN excluded.ai_state IN ('PASS','VETO','UNAVAILABLE')
                    THEN excluded.ai_state ELSE paper_scans.ai_state END,
              priority=MAX(paper_scans.priority,excluded.priority),
              equity=COALESCE(excluded.equity,paper_scans.equity),
              cash=COALESCE(excluded.cash,paper_scans.cash),
              fee_shadow_state=CASE
                  WHEN excluded.fee_shadow_state != 'NOT_INVOKED'
                    THEN excluded.fee_shadow_state
                  ELSE COALESCE(paper_scans.fee_shadow_state,'NOT_INVOKED')
              END""",values)
        db.execute("DELETE FROM paper_scans WHERE minute<?",
            (values[1]-30*86400,))

def read_scorecards(directory,*,now=None,hours=24):
    if hours not in (24,168):raise ValueError("INVALID_SCORECARD_WINDOW")
    cards={s:{"symbol":s,"state":"NOT_RECORDED",
              "sample_minutes":0,"signal_minutes":0,"fill_minutes":0,
              "no_signal_minutes":0,"data_error_minutes":0,
              "ai_shadow":{v:0 for v in STATES},
              "synthetic_pnl_usd":None,"max_paper_drawdown_pct":None}
           for s in SYMBOLS}
    path=Path(directory)/DB_NAME
    try:
        st=path.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_mode&0o077 or st.st_size>32_000_000:
            return cards
        now=now or datetime.now(timezone.utc)
        cutoff=int((now-timedelta(hours=hours)).timestamp())
        with sqlite3.connect("file:"+str(path)+"?mode=ro",uri=True,timeout=2) as db:
            rows=db.execute("""SELECT symbol,minute,state,signal,ai_state,equity
                FROM paper_scans WHERE minute>=?
                ORDER BY symbol,minute LIMIT 15000""",(cutoff,)).fetchall()
    except (OSError,sqlite3.Error,ValueError):
        return cards
    for symbol,minute,state,signal,ai_state,equity in rows:
        card=cards.get(symbol)
        if card is None:continue
        card["state"]="OBSERVED"
        card["sample_minutes"]+=1
        card["last_scan_minute"]=datetime.fromtimestamp(minute,timezone.utc).isoformat()
        if signal in ("BUY","SELL"):card["signal_minutes"]+=1
        if state=="FILLED":card["fill_minutes"]+=1
        elif state=="NO_SIGNAL":card["no_signal_minutes"]+=1
        elif state in ("DATA_UNAVAILABLE","GAPPED_BARS","STALE_CANDLES"):
            card["data_error_minutes"]+=1
        if ai_state in card["ai_shadow"]:card["ai_shadow"][ai_state]+=1
        if equity is not None:
            try:
                current=Decimal(equity)
                peak=max(Decimal(card.get("_peak","1000")),current)
                card["_peak"]=str(peak)
                dd=(peak-current)*100/peak if peak else Decimal(0)
                card["_dd"]=str(max(Decimal(card.get("_dd","0")),dd))
                card["synthetic_pnl_usd"]=str((current-Decimal("1000")).quantize(Decimal("0.01")))
            except (ArithmeticError,InvalidOperation):pass
    for card in cards.values():
        if "_dd" in card:
            card["max_paper_drawdown_pct"]=str(Decimal(card.pop("_dd")).quantize(Decimal("0.01")))
        card.pop("_peak",None)
    return cards
