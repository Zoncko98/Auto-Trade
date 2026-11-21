"""V2 live-migration contract tests: offline mocked broker, NEVER real orders."""
from __future__ import annotations
from datetime import datetime,timezone,timedelta
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,main
from unittest.mock import Mock
from trader_v2.contracts import BrokerExecution
from trader_v2.engine import candidate_key
from trader_v2.live_pipeline import LivePipeline,WriterHandoff,LiveMigrationRejected
from trader_v2.models import (
    Account,AssetClass,AuthState,Capability,Candidate,MarketSnapshot,
    OrderSide,RiskPolicy
)
from trader_v2.store import EventStore,IntentConflict

class FakeLiveBroker:
    provider_id="robinhood_crypto"
    def __init__(self):
        self.sends=0;self.order=None;self.exception=None
        self.accounts=0
    def account(self,id):
        self.accounts+=1
        return Account(id,self.provider_id,
            Capability(frozenset({AssetClass.CRYPTO}),fractional=True),
            D("100"),D("150"),{},AuthState.CONNECTED,True,D("0"))
    def submit(self,intent):
        self.sends+=1
        self.order=BrokerExecution(intent.key,"FILLED","SIGNED-ORDER-123",
           intent.quantity,intent.limit_price,D("0.01"))
        if self.exception is not None:raise self.exception
        return self.order
    def find_order(self,key):
        return self.order if self.order and self.order.key==key else None

class TestLiveCutover(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=EventStore(Path(self.temp.name)/"orders.sqlite3")
        self.broker=FakeLiveBroker()
        self.now=datetime.now(timezone.utc).replace(microsecond=0)
        self.quote=MarketSnapshot("BTC-USD",AssetClass.CRYPTO,"robinhood_signed",
             self.now,self.now,D("10"),D("10.01"),D("10"),True)
        self.candidate=Candidate("crypto_sma","migrate-1","crypto-account",
             "BTC-USD",AssetClass.CRYPTO,OrderSide.BUY,
             self.now,{"indicator":"validated_replay"})
        self.policy=RiskPolicy(max_order_notional=D("10"),max_total_exposure=D("50"),
             max_position_fraction=D("0.5"),max_snapshot_age_seconds=90)
        self.gate=Mock(side_effect=lambda:self.proof())
        self.pipe=LivePipeline(self.broker,self.store,self.gate)
    def proof(self,**kwargs):
        args=dict(broker="robinhood_crypto",account_id="crypto-account",
          generation="handoff-1",checked_at=self.now,
          expires_at=self.now+timedelta(seconds=45),
          operator_armed=True,v1_writer_stopped=True,local_orders_resolved=True,
          broker_open_orders_resolved=True,account_verified=True,
          settled_funding_verified=True,session_verified=True)
        args.update(kwargs)
        return WriterHandoff(**args)
    def evaluate(self,**kwargs):
        return self.pipe.evaluate(self.candidate,self.quote,self.policy,
                now=self.now,**kwargs)

    def test_no_handoff_no_live_order(self):
        self.gate.side_effect=lambda:None
        out=self.evaluate()
        self.assertEqual(out.reason,"V1_TO_V2_SINGLE_WRITER_HANDOFF_UNVERIFIED")
        self.assertEqual(self.broker.sends,0)
        self.assertEqual(self.store.summary()["intents"],0)

    def test_operator_disarmed_or_v1_still_active_never_submits(self):
        for name in ("operator_armed","v1_writer_stopped","local_orders_resolved",
                     "broker_open_orders_resolved","account_verified",
                     "settled_funding_verified","session_verified"):
            with self.subTest(name=name):
                self.gate.side_effect=lambda n=name:self.proof(**{n:False})
                self.assertEqual(self.evaluate().code,"BLOCKED")
                self.assertEqual(self.broker.sends,0)

    def test_cross_account_and_expired_proofs_rejected(self):
        for proof in (self.proof(account_id="wrong-account"),
                      self.proof(checked_at=self.now-timedelta(seconds=20),expires_at=self.now-timedelta(seconds=10))):
            with self.subTest(proof=proof):
                self.gate.side_effect=lambda p=proof:p
                self.assertEqual(self.evaluate().code,"BLOCKED")
        self.assertEqual(self.broker.sends,0)

    def test_unverified_public_data_no_orders(self):
        self.quote=MarketSnapshot("BTC-USD",AssetClass.CRYPTO,"coinbase_public",
            self.now,self.now,D("10"),D("10.01"),D("10"),True)
        self.assertEqual(self.evaluate().reason,"EXECUTABLE_BROKER_QUOTE_UNVERIFIED")
        self.assertEqual(self.broker.sends,0)

    def test_exact_one_real_broker_post_and_idempotent_recovery(self):
        first=self.evaluate()
        second=self.evaluate()
        self.assertEqual(first.code,"FILLED")
        self.assertEqual(second.code,"FILLED")
        self.assertEqual(self.broker.sends,1)
        self.assertEqual(self.store.summary()["intents"],1)
        self.assertEqual(self.store.summary()["unresolved"],0)

    def test_after_broker_fill_network_loss_reconciles_without_repost(self):
        self.broker.exception=TimeoutError("Lost connection after accepted order")
        first=self.evaluate()
        self.assertEqual(first.code,"RECONCILIATION_REQUIRED")
        self.assertEqual(self.store.summary()["unresolved"],1)
        self.assertEqual(self.broker.sends,1)
        recovered=self.pipe.reconcile(first.intent_key)
        self.assertEqual(recovered.code,"FILLED")
        self.assertEqual(self.evaluate().code,"FILLED")
        self.assertEqual(self.broker.sends,1)

    def test_no_receipt_without_broker_lookup_holds_lock(self):
        self.broker.exception=TimeoutError("Unknown reply")
        self.broker.find_order=Mock(return_value=None)
        first=self.evaluate()
        second=self.evaluate()
        self.assertEqual(first.code,"RECONCILIATION_REQUIRED")
        self.assertEqual(second.code,"RECONCILIATION_REQUIRED")
        self.assertEqual(self.broker.sends,1)

    def test_definitive_broker_rejection_is_terminal(self):
        self.broker.exception=LiveMigrationRejected("definite")
        one=self.evaluate()
        self.assertEqual(one.code,"REJECTED")
        self.assertEqual(self.store.summary()["unresolved"],0)
        self.assertEqual(self.evaluate().code,"REJECTED")
        self.assertEqual(self.broker.sends,1)

    def test_handoff_revoked_between_risk_and_submit_no_post(self):
        calls=[self.proof(),None]
        self.gate.side_effect=lambda:calls.pop(0)
        out=self.evaluate()
        self.assertEqual(out.reason,"HANDOFF_OR_QUOTE_EXPIRED_BEFORE_ORDER")
        self.assertEqual(self.broker.sends,0)
        self.assertEqual(self.store.summary()["unresolved"],1)

    def test_handoff_generation_change_no_post(self):
        calls=[self.proof(),self.proof(generation="handoff-2")]
        self.gate.side_effect=lambda:calls.pop(0)
        out=self.evaluate()
        self.assertEqual(out.reason,"HANDOFF_OR_QUOTE_EXPIRED_BEFORE_ORDER")
        self.assertEqual(self.broker.sends,0)

    def test_signed_quote_still_needs_live_market_session(self):
        self.quote=MarketSnapshot("BTC-USD",AssetClass.CRYPTO,"robinhood_signed",
            self.now,self.now,D("10"),D("10.01"),D("10"),False)
        self.assertEqual(self.evaluate().reason,"MARKET_SESSION_CLOSED")
        self.assertEqual(self.broker.sends,0)

    def test_inactive_account_and_fee_guard(self):
        self.broker.account=lambda id:Account(
            id,"robinhood_crypto",Capability(frozenset({AssetClass.CRYPTO}),fractional=True),
            D("10"),D("10"),{},AuthState.CONNECTED,False)
        self.assertEqual(self.evaluate().reason,"ACCOUNT_DISARMED")
        self.assertEqual(self.broker.sends,0)

    def test_sim_broker_never_accepted_as_live(self):
        from trader_v2.simulation import SimulatedBroker
        sim=SimulatedBroker(Path(self.temp.name)/"sim.sqlite3")
        with self.assertRaises(TypeError):
            LivePipeline(sim,self.store,self.gate)

    def test_permit_invalid_boolean_and_time_fail_closed(self):
        for item in (dict(operator_armed=1),
                     dict(expires_at=self.now+timedelta(minutes=5))):
            with self.subTest(item=item),self.assertRaises(ValueError):
                self.proof(**item)

    def test_canonical_journal_atomic_pending_guard_under_race(self):
        from trader_v2.models import OrderIntent,RiskDecision
        from concurrent.futures import ThreadPoolExecutor
        barrier=__import__("threading").Barrier(2)
        def write(i):
            intent=OrderIntent("live-signal-"+str(i),"crypto-account","crypto_sma",
                 "BTC-USD",AssetClass.CRYPTO,OrderSide.BUY,D("1"),D("10"),self.now)
            risk=RiskDecision("PASS","TEST",D("1"),D("10"),D("10"))
            barrier.wait()
            try:return self.store.prepare(intent,risk)["state"]
            except IntentConflict:return "CONFLICT"
        with ThreadPoolExecutor(max_workers=2) as pool:
            a,b=list(pool.map(write,[1,2]))
        self.assertEqual(sorted((a,b)),["CONFLICT","INTENT_PERSISTED"])
        self.assertEqual(self.store.summary()["intents"],1)

if __name__=="__main__":
    main()
