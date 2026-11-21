"""Persistent V2 fresh-market crypto paper worker, fully broker independent.

Public Coinbase ticker observations -> real completed one-minute candles ->
V2 CryptoController -> deterministic risk -> durable idempotent intent ->
SimulatedBroker. This has NO live broker adapters and does not invoke AI yet.
"""
from __future__ import annotations

from datetime import datetime,timezone
from decimal import Decimal
from pathlib import Path
from contextlib import contextmanager
import argparse
import fcntl
import json
import os
import signal
import sqlite3
import stat
import time

from .models import AssetClass,Candle,RiskPolicy,utc
from .strategies import CryptoController
from .engine import PaperPipeline
from .store import EventStore
from .simulation import SimulatedBroker
from .public_crypto import PRODUCTS,PublicFeedError,fetch_ticker
from .ai_shadow import shadow_review
from .recorded_replay import _atomic_json, _private_json
from .scan_observability import capture_scan,read_scorecards
from .paper_activity import read_activity
from .sim_economics import read_economics

STATE_VERSION="live-crypto-paper-1"
INTERVAL_SECONDS=30
MAX_BARS=240
_CONTROLLER=CryptoController()
_STOP=False


class FreshPaperError(ValueError):
    pass


def _private(path):
    if path.is_symlink():raise FreshPaperError("PAPER_DIRECTORY_UNSAFE")
    path.mkdir(parents=True,mode=0o700,exist_ok=True)
    if not stat.S_ISDIR(path.stat().st_mode) or path.stat().st_mode & 0o077:
        raise FreshPaperError("PAPER_DIRECTORY_UNSAFE")
    return path


@contextmanager
def _lock(root):
    _private(root)
    fd=os.open(root/"scan.lock",os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        st=os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_mode & 0o077:
            raise FreshPaperError("PAPER_LOCK_UNSAFE")
        try:
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise FreshPaperError("PAPER_SCAN_ALREADY_RUNNING") from None
        yield
    finally:
        fcntl.flock(fd,fcntl.LOCK_UN)
        os.close(fd)


def _db(root):
    path=root/"tick_bars.sqlite3"
    if path.is_symlink():raise FreshPaperError("TICK_DATABASE_UNSAFE")
    if not path.exists():
        try:
            fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            os.close(fd)
        except FileExistsError:
            pass
    if path.stat().st_mode&0o077:raise FreshPaperError("TICK_DATABASE_UNSAFE")
    conn=sqlite3.connect(str(path),timeout=8,isolation_level=None)
    conn.row_factory=sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.executescript("""CREATE TABLE IF NOT EXISTS tick_bars(
            symbol TEXT NOT NULL,
            minute_start INTEGER NOT NULL,
            quote_at TEXT NOT NULL,
            close TEXT NOT NULL,
            PRIMARY KEY(symbol,minute_start));""")
        return conn
    except BaseException:
        conn.close()
        raise


def _record_and_closed_bars(conn, quote, now):
    # Persist the last real trade observation from each UTC minute. No
    # forward-filled missing bars and no synthetic history.
    bucket=int(quote.observed_at.timestamp())//60*60
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("""INSERT INTO tick_bars VALUES(?,?,?,?)
            ON CONFLICT(symbol,minute_start) DO UPDATE SET
                quote_at=excluded.quote_at,close=excluded.close
            WHERE excluded.quote_at>tick_bars.quote_at""",
            (quote.symbol,bucket,quote.observed_at.isoformat(),str(quote.last)))
        # Old candles are not needed for the current SMA; trim bounded by age.
        conn.execute("DELETE FROM tick_bars WHERE minute_start<?",
                     (int(now.timestamp())-86400,))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    current_bucket=int(now.timestamp())//60*60
    rows=conn.execute("""SELECT minute_start,close FROM tick_bars
          WHERE symbol=? AND minute_start<?
          ORDER BY minute_start DESC LIMIT ?""",
          (quote.symbol,current_bucket,MAX_BARS)).fetchall()
    bars=[Candle(quote.symbol,
          datetime.fromtimestamp(r["minute_start"]+60,timezone.utc),
          Decimal(r["close"]),closed=True) for r in reversed(rows)]
    return bars


def _today_counts(broker, account, now):
    # Actual simulated fills from broker's separate authoritative ledger,
    # not in-memory counters that reset after a worker restart.
    with sqlite3.connect(str(broker.path),timeout=5) as db:
        rows=db.execute("""SELECT intent_document,created_at
            FROM sim_orders WHERE account_id=?""",(account,)).fetchall()
    entries=exits=0
    for doc,at in rows:
        try:
            if utc(datetime.fromisoformat(at)).date()!=now.date():
                continue
            side=json.loads(doc).get("side")
            if side=="BUY":entries+=1
            elif side=="SELL":exits+=1
        except (ValueError,TypeError,KeyError):
            # Bad fills must stop new submissions rather than bypass quotas.
            raise FreshPaperError("SIMULATED_ORDER_COUNT_UNVERIFIED") from None
    return entries,exits


def run_once(state_dir,symbol,*,fetch=fetch_ticker,now=None,shadow=shadow_review):
    if symbol not in PRODUCTS:raise FreshPaperError("UNSUPPORTED_PUBLIC_PAPER_SYMBOL")
    fixed_clock=now is not None
    now=utc(now or datetime.now(timezone.utc))
    root=Path(state_dir)/"v2"/"fresh_paper"
    _private(root.parent)
    with _lock(root):
        path=root/(symbol.lower()+".json")
        try:
            quote=fetch(symbol,now=now if fixed_clock else None)
            if not fixed_clock:
                now=utc(datetime.now(timezone.utc))
            if quote.symbol!=symbol or quote.asset_class is not AssetClass.CRYPTO:
                raise FreshPaperError("PUBLIC_TICKER_IDENTITY_INVALID")
            # Do not permit a caller to provide a previous/forward-looking tick.
            age=(now-quote.observed_at).total_seconds()
            if age < -2 or age > 90:
                raise FreshPaperError("PUBLIC_TICKER_STALE_OR_FUTURE")
            feed=_db(root)
            try: bars=_record_and_closed_bars(feed,quote,now)
            finally:feed.close()
            account="v2-paper-"+symbol.lower()
            broker=SimulatedBroker(root/"sim.sqlite3",
                          fee_bps=Decimal("5"),slippage_bps=Decimal("5"),
                          clock=lambda:now)
            broker.seed(account,AssetClass.CRYPTO,Decimal("1000"),fractional=True)
            broker.quote(quote)
            journal=EventStore(root/"intents.sqlite3")
            state="WARMING_UP"
            reason="WAITING_FOR_REAL_CLOSED_CANDLES"
            signal=None
            outcome=None
            ai_evidence={"state":"NOT_INVOKED","changed_order_authority":False}
            if len(bars)>=_CONTROLLER.long+1:
                last=bars[-(_CONTROLLER.long+1):]
                # Missing source minutes cannot be filled from fabricated prices.
                if any((b.observed_at-a.observed_at).total_seconds()!=60
                       for a,b in zip(last,last[1:])):
                    state="GAPPED_BARS"
                    reason="WAITING_FOR_CONTIGUOUS_REAL_MINUTES"
                elif (now-last[-1].observed_at).total_seconds()>90:
                    state="STALE_CANDLES"
                    reason="NO_RECENT_CLOSED_MARKET_CANDLE"
                else:
                    candidate=_CONTROLLER.candidate(account,bars)
                    if candidate is None:
                        state="NO_SIGNAL"
                        reason="NO_QUALIFIED_SMA_CROSS"
                    else:
                        # AI shadow has no effect on the no-AI baseline.
                        # Record verified PASS/VETO/UNAVAILABLE for comparison.
                        ai_evidence=shadow(candidate,quote,now=now)
                        if not fixed_clock:
                            now=utc(datetime.now(timezone.utc))
                        entries,exits=_today_counts(broker,account,now)
                        result=PaperPipeline(broker,journal).evaluate(
                            candidate,quote,RiskPolicy(ai_mode="OFF"),
                            now=now,entries_today=entries,exits_today=exits)
                        signal=candidate.side.value
                        state=result.code
                        reason=result.reason
                        outcome=result.intent_key
            wallet=broker.account(account)
            report={
                "version":STATE_VERSION,"symbol":symbol,
                "source":"COINBASE_PUBLIC_TICKER_ONLY",
                "market_executable_for_user_broker":False,
                "simulated_only":True,"ai_mode":"OFF_BASELINE",
                "ai_shadow_mode":"ADVISORY_NO_ORDER_AUTHORITY",
                "live_orders_submitted":0,"at":now.isoformat(),
                "last_quote_at":quote.observed_at.isoformat(),
                "closed_bars":len(bars),
                "ready_closed_bars":_CONTROLLER.long+1,
                "last_closed_bar_at":bars[-1].observed_at.isoformat() if bars else None,
                "scan_state":state,"reason":reason,
                "signal":signal,"intent_key":outcome,
                "ai_shadow":ai_evidence,
                "virtual_cash":str(wallet.cash),
                "virtual_equity":str(wallet.equity),
                "virtual_positions":{s:str(v) for s,v in wallet.positions.items()},
                "journal":journal.summary(),
            }
        except (PublicFeedError,FreshPaperError) as exc:
            report={"version":STATE_VERSION,"symbol":symbol,
                    "source":"COINBASE_PUBLIC_TICKER_ONLY","at":now.isoformat(),
                    "scan_state":"DATA_UNAVAILABLE","reason":str(exc)[:85],
                    "simulated_only":True,
                    "market_executable_for_user_broker":False,
                    "live_orders_submitted":0,"ai_mode":"OFF_BASELINE"}
        try:
            capture_scan(root,report)
            report["scan_history"]="PERSISTED"
        except (ValueError,PermissionError,OSError,sqlite3.Error):
            # A failed diagnostic write never changes paper order authority.
            report["scan_history"]="UNAVAILABLE"
        _atomic_json(path,report)
        return report


def status(state_dir):
    base=Path(state_dir)/"v2"/"fresh_paper"
    reports=[]
    now=datetime.now(timezone.utc)
    for symbol in PRODUCTS:
        record=_private_json(base/(symbol.lower()+".json"))
        if record is None or record.get("version")!=STATE_VERSION:
            reports.append({"symbol":symbol,"scan_state":"NOT_SCANNED"})
            continue
        observed=record.get("at")
        try:
            age=int((now-utc(datetime.fromisoformat(observed))).total_seconds())
        except (ValueError,TypeError):
            age=None
        report=dict(record)
        report["heartbeat_age_sec"]=age
        if age is None or age>180 or age< -2:
            report["scan_state"]="WORKER_STALE"
            report["reason"]="PAPER_WORKER_HEARTBEAT_UNVERIFIED"
        reports.append(report)
    return {"mode":"INDEPENDENT_V2_CRYPTO_PAPER",
            "live_orders_authorized":False,"broker_credentials_used":False,
            "market_executable_for_user_broker":False,
            "sources":["COINBASE_PUBLIC_TICKER_ONLY"],
            "ai_mode":"OFF_BASELINE","reports":reports,
            "scorecards":read_scorecards(base),
            "activity_3h":read_activity(base,hours=3,now=now),
            "activity_24h":read_activity(base,hours=24,now=now),
            "economic_reconciliation":read_economics(base,now=now)}


def _signal_stop(_sig,_frame):
    global _STOP
    _STOP=True


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--state-dir",required=True)
    args=parser.parse_args()
    signal.signal(signal.SIGTERM,_signal_stop)
    signal.signal(signal.SIGINT,_signal_stop)
    while not _STOP:
        start=time.monotonic()
        for symbol in PRODUCTS:
            if _STOP:break
            try:
                outcome=run_once(args.state_dir,symbol)
                print("V2 paper",symbol,outcome["scan_state"],outcome.get("reason",""),
                      flush=True)
            except Exception as exc:
                print("V2 paper",symbol,"ERROR",type(exc).__name__,flush=True)
        while not _STOP and time.monotonic()-start<INTERVAL_SECONDS:
            time.sleep(1)


if __name__=="__main__":
    main()
