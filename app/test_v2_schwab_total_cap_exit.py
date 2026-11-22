"""Schwab total order cap may not veto a separate verified protective exit."""
import json
from datetime import datetime,timezone,timedelta
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from trader_v2.autonomous_live import AutonomousLiveScan
from trader_v2.account_exit_rules import ManagedExitLot,ExitPolicy
from trader_v2.v1_order_inheritance import InheritedOrderLimits
from trader_v2.models import (Account,Capability,AssetClass,AuthState,
                              MarketSnapshot,Candle,RiskPolicy)
from trader_v2.contracts import BrokerExecution
from trader_v2.live_pipeline import WriterHandoff
from trader_v2.writer_ownership import _paths

NOW=datetime.now(timezone.utc).replace(microsecond=0)

class StockBroker:
    provider_id="schwab"
    writer_scope_account="acct"
    def __init__(self,holding):
        self.held={"AAPL":D("1")} if holding else {}
        self.posts=0
        self.last=None
    def account(self,account_id):
        return Account(account_id,"schwab",
            Capability(frozenset({AssetClass.STOCK}),fractional=False,
                min_notional=D("1"),quantity_increment=D("1"),
                price_increment=D("0.01")),
            D("50"),D("100"),self.held,AuthState.CONNECTED,True,D("50"))
    def submit(self,intent):
        self.posts+=1
        self.last=BrokerExecution(intent.key,"FILLED","broker-fill",
            intent.quantity,intent.limit_price,D("0"))
        return self.last
    def find_order(self,key):
        return self.last if self.last and self.last.key==key else None

def closed_m5(down):
    last=NOW-timedelta(minutes=5)
    vals=[D("11")]*5+[D("10")] if down else [D("10")]*5+[D("11")]
    return [Candle("AAPL",last-timedelta(minutes=5*(5-i)),v,True)
            for i,v in enumerate(vals)]

class SchwabCapExitTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state=Path(self.tmp.name)
        _,record,digest=_paths(self.state,"schwab","acct")
        record.write_text(json.dumps({"schema":1,"broker":"schwab",
            "account_digest":digest,"owner":"V2","generation":"generation-123"}))
        record.chmod(0o600)
        self.policy=RiskPolicy(max_order_notional=D("15"),
            max_total_exposure=D("75"),max_position_fraction=D("0.5"),
            max_entries_per_day=2,max_exit_orders_per_day=3,ai_mode="REQUIRED")
    def scanner(self,broker,down):
        inherited=InheritedOrderLimits("schwab","acct",0,1,
                  frozenset(),False,True,True,1)
        q=MarketSnapshot("AAPL",AssetClass.STOCK,"schwab_signed",
             NOW-timedelta(seconds=1),NOW,D("10"),D("10.01"),D("10"),True)
        return AutonomousLiveScan(broker,"acct",state_dir=self.state,
            symbols=["AAPL"],asset_class=AssetClass.STOCK,clock=lambda:NOW,
            candle_feed=lambda s:closed_m5(down),
            quote_feed=lambda s:q,
            gate=lambda:WriterHandoff("schwab","acct","generation-123",
                NOW,NOW+timedelta(seconds=60),True,True,True,True,True,True,True),
            policy_provider=lambda a:self.policy,
            realized_loss_provider=lambda a:D("0"),
            strategy_parity_provider=lambda:True,
            v1_activity_provider=lambda a,now:inherited,
            exit_policy_provider=lambda a:ExitPolicy("schwab"),
            exit_evidence_provider=lambda s,a:ManagedExitLot(
                "AAPL",D("1"),D("1"),D("12"),
                NOW-timedelta(days=3),
                cost_basis_broker_verified=True,
                original_fills_reconciled=True))
    def test_protective_exit_still_runs_when_v1_total_day_limit_reached(self):
        broker=StockBroker(holding=True)
        status=self.scanner(broker,down=True).run_once()
        self.assertEqual(status["state"],"FILLED",status)
        self.assertEqual(broker.posts,1)
    def test_new_entry_blocked_when_v1_total_day_limit_reached(self):
        broker=StockBroker(holding=False)
        status=self.scanner(broker,down=False).run_once()
        self.assertEqual(status["state"],"NO_VALIDATED_V2_SIGNAL",status)
        self.assertIn("V1_SCHWAB_TOTAL_ORDER_NEW_ENTRY_CAP_REACHED",status["reason"])
        self.assertEqual(broker.posts,0)
