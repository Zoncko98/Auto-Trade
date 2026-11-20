"""Explicit deterministic V2 paper-only smoke run. Not scheduled; never connects live brokers.

Usage:
  AUTO_TRADER_V2_ENABLED=true python -m trader_v2.demo --state-dir /tmp/v2-demo
"""
from __future__ import annotations
import argparse,json,os
from datetime import datetime,timezone
from decimal import Decimal
from pathlib import Path
from .models import AssetClass,MarketSnapshot,Candidate,OrderSide,RiskPolicy
from .simulation import SimulatedBroker
from .store import EventStore
from .engine import PaperPipeline

def run_demo(state_dir):
    if os.environ.get("AUTO_TRADER_V2_ENABLED","false").lower()!="true":
        raise RuntimeError("V2 paper demo is disabled; set AUTO_TRADER_V2_ENABLED=true explicitly")
    root=Path(state_dir)/"v2"
    now=datetime.now(timezone.utc)
    root.mkdir(mode=0o700,parents=True,exist_ok=True)
    if root.stat().st_mode & 0o077:
        raise PermissionError("V2 paper state must be owner-only")
    signal_file=root/"demo_signal_at.txt"
    try:
        fd=os.open(signal_file,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            f.write(now.isoformat())
            f.flush()
            os.fsync(f.fileno())
    if signal_file.stat().st_mode & 0o077:
        raise PermissionError("Unsafe synthetic signal metadata")
    signal_time=datetime.fromisoformat(signal_file.read_text(encoding="utf-8"))
    broker=SimulatedBroker(root/"simulation.sqlite3",fee_bps=Decimal("5"))
    broker.seed("v2-paper-stock",AssetClass.STOCK,Decimal("1000"))
    market=MarketSnapshot("DEMO",AssetClass.STOCK,"synthetic-fixture",now,now,
        Decimal("9.99"),Decimal("10.00"),Decimal("10.00"),True)
    broker.quote(market)
    store=EventStore(root/"events.sqlite3")
    pipeline=PaperPipeline(broker,store)
    signal=Candidate("stock_fixture","1","v2-paper-stock","DEMO",AssetClass.STOCK,
        OrderSide.BUY,signal_time,{"indicator":"SYNTHETIC_TEST_ONLY"})
    result=pipeline.evaluate(signal,market,
       RiskPolicy(max_order_notional=Decimal("100"),
                  max_total_exposure=Decimal("300"),max_position_fraction=Decimal("0.5")),
       now=now)
    return {"result":result.code,"order_state":result.order_state,
            "virtual_cash":str(broker.account("v2-paper-stock").cash),
            "virtual_positions":{k:str(v) for k,v in
                                  broker.account("v2-paper-stock").positions.items()},
            "event_store":store.summary(),"live_orders_submitted":0,
            "market_data":"SYNTHETIC_ONLY"}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--state-dir",required=True)
    args=parser.parse_args()
    print(json.dumps(run_demo(args.state_dir),sort_keys=True))

if __name__=="__main__":main()
