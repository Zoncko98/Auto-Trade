"""Shared V2 autonomous crypto/stock live scan, broker-mock E2E tests."""
from datetime import datetime,timezone,timedelta
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,main
from trader_v2.models import (Account,AssetClass,AuthState,Capability,
    OrderSide,RiskPolicy,MarketSnapshot,Candle,AIReview,AIState)
from trader_v2.contracts import BrokerExecution
from trader_v2.live_pipeline import WriterHandoff
from trader_v2.writer_ownership import _paths
from trader_v2.autonomous_live import AutonomousLiveScan,accepted_bars,LiveScanUnavailable
from trader_v2.account_exit_rules import ManagedExitLot,ExitPolicy
from trader_v2.v1_order_inheritance import InheritedOrderLimits
import json

NOW=datetime.now(timezone.utc).replace(microsecond=0)

def bars(now,symbol="BTC-USD",direction="BUY",gap=False):
 at=now-timedelta(seconds=60)
 vals=[D("10")]*8+[D("11") if direction=="BUY" else D("9")]
 if direction=="SELL":vals=[D("11")]*8+[D("10")]
 rows=[Candle(symbol,at-timedelta(seconds=60*(8-i)),
       v,closed=True) for i,v in enumerate(vals)]
 if gap:
  rows[5]=Candle(symbol,rows[5].observed_at-timedelta(seconds=60),
                 rows[5].close,closed=True)
 return rows

class Broker:
 provider_id="robinhood_crypto"
 def __init__(self):self.posts=0;self.last=None;self.held={}
 def account(self,aid):
  return Account(aid,self.provider_id,
      Capability(frozenset({AssetClass.CRYPTO}),fractional=True,
        min_notional=D("1"),quantity_increment=D(".001")),
      D("100"),D("100"),self.held,AuthState.CONNECTED,True,D("0"))
 def submit(self,intent):
  self.posts+=1
  self.last=BrokerExecution(intent.key,"FILLED","signed-verified-order-1",
            intent.quantity,intent.limit_price,D("0.02"))
  return self.last
 def find_order(self,key):return self.last if self.last and self.last.key==key else None

class Reviewer:
 def __init__(self,now):self.now=now
 def review(self,candidate,quote):
  return AIReview(AIState.PASS,candidate.symbol,self.now,
         self.now+timedelta(seconds=60),"mock-ollama","Validated pattern")

class AutonomousLiveScanTests(TestCase):
 def setUp(self):
  self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.state=Path(self.tmp.name)
  self.now=datetime.now(timezone.utc).replace(microsecond=0)
  self.broker=Broker()
  self.stock=False
  self.price=MarketSnapshot("BTC-USD",AssetClass.CRYPTO,"robinhood_signed",
      self.now-timedelta(seconds=1),self.now,D("10"),D("10.01"),
      D("10.005"),True)
  self.owner=None
  self.proof=lambda:WriterHandoff("robinhood_crypto","acct","generation-123",
     self.now,self.now+timedelta(seconds=60),True,True,True,True,
     True,True,True)
  self.policy=RiskPolicy(max_order_notional=D("15"),
      max_total_exposure=D("75"),max_position_fraction=D(".5"),
      max_entries_per_day=2,max_exit_orders_per_day=3,ai_mode="REQUIRED")
  self.loss=lambda account:D("0")
  self.legacy=InheritedOrderLimits("robinhood_crypto","acct",0,0,
        frozenset(),False,True,True)
  self.make_lot=lambda symbol,account:ManagedExitLot(
    symbol,account.positions[symbol],account.positions[symbol],D("12"),
    self.now-timedelta(minutes=30),high_water_bid=D("11"),
    cost_basis_broker_verified=True,original_fills_reconciled=True)
  self.engine=lambda direction="BUY",gap=False,reviewer=None:AutonomousLiveScan(
    self.broker,"acct",state_dir=self.state,symbols=["BTC-USD"],
    asset_class=AssetClass.CRYPTO,candle_feed=lambda symbol:bars(self.now,symbol,direction,gap),
    quote_feed=lambda symbol:self.price,gate=self.proof,
    reviewer=reviewer if reviewer is not None else Reviewer(self.now),
    policy_provider=lambda account:self.policy,
    realized_loss_provider=self.loss,
    strategy_parity_provider=lambda:True,clock=lambda:self.now,
    exit_evidence_provider=lambda symbol,account:self.make_lot(symbol,account),
    exit_policy_provider=lambda account:ExitPolicy("robinhood_crypto"),
    v1_activity_provider=lambda account,now:self.legacy)
 def own_v2(self):
  _,rec,digest=_paths(self.state,"robinhood_crypto","acct")
  rec.write_text(json.dumps({"schema":1,"broker":"robinhood_crypto",
   "account_digest":digest,"owner":"V2","generation":"generation-123"}))
  rec.chmod(0o600)
  return rec
 def test_stock_six_real_completed_bars_are_eligible(self):
  at=self.now-timedelta(seconds=120)
  vals=[D('10')]*5+[D('11')]
  rows=[Candle('F',at-timedelta(minutes=5*(5-i)),v,closed=True)
        for i,v in enumerate(vals)]
  self.assertEqual(len(accepted_bars(rows,'F',AssetClass.STOCK,self.now)),6)
 def test_v1_owned_never_creates_new_live_journal_or_posts(self):
  out=self.engine().run_once()
  self.assertEqual(out["state"],"V2_OWNER_PROOF_UNAVAILABLE")
  self.assertFalse((self.state/"v2/events.sqlite3").exists())
  self.assertEqual(self.broker.posts,0)
 def test_confirmed_owner_and_signal_one_post_journal_and_receipt(self):
  self.own_v2()
  out=self.engine().run_once()
  self.assertEqual(out["state"],"FILLED")
  self.assertEqual(self.broker.posts,1)
  self.assertTrue((self.state/"v2/events.sqlite3").exists())
  repeat=self.engine().run_once()
  self.assertEqual(self.broker.posts,1)
  self.assertEqual(repeat["state"],"FILLED")
 def test_unverified_v1_exit_and_cooldown_parity_blocks_before_new_journal(self):
  self.own_v2()
  engine=self.engine()
  engine.strategy_parity_provider=None
  status=engine.run_once()
  self.assertEqual(status['state'],'V2_STRATEGY_PARITY_UNVERIFIED')
  self.assertFalse((self.state/'v2/events.sqlite3').exists())
  self.assertEqual(self.broker.posts,0)
 def test_generation_revoked_v1_locked(self):
  rec=self.own_v2()
  data=json.loads(rec.read_text());data["generation"]="different-123"
  rec.write_text(json.dumps(data));rec.chmod(0o600)
  self.assertEqual(self.engine().run_once()["state"],"V2_OWNER_PROOF_UNAVAILABLE")
  self.assertEqual(self.broker.posts,0)
 def test_invalid_or_gapped_public_candles_never_create_intent(self):
  self.own_v2()
  out=self.engine(gap=True).run_once()
  self.assertEqual(out["state"],"NO_VALIDATED_V2_SIGNAL")
  self.assertEqual(self.broker.posts,0)
 def test_required_model_unavailable_blocks_buy(self):
  self.own_v2()
  eng=self.engine();eng.reviewer=None
  out=eng.run_once()
  self.assertEqual(out["state"],"V2_RISK_POLICY_UNVERIFIED")
  self.assertEqual(self.broker.posts,0)
 def test_unknown_daily_pnl_or_loss_limit_never_ignored(self):
  self.own_v2()
  self.loss=lambda account:None
  self.assertEqual(self.engine().run_once()["state"],"V2_RISK_POLICY_UNVERIFIED")
  self.loss=lambda account:D("100")
  out=self.engine().run_once()
  self.assertEqual(out["state"],"BLOCKED")
  self.assertEqual(self.broker.posts,0)
 def test_protective_sell_does_not_require_entry_only_ai_mode(self):
  self.own_v2()
  self.broker.held={"BTC-USD":D("1")}
  self.policy=RiskPolicy(max_order_notional=D("15"),
    max_total_exposure=D("75"),max_position_fraction=D(".5"),
    max_entries_per_day=2,max_exit_orders_per_day=3,ai_mode="OFF")
  eng=self.engine(direction="SELL");eng.reviewer=None
  out=eng.run_once()
  self.assertEqual(out["state"],"FILLED")
  self.assertEqual(self.broker.posts,1)

 def test_buy_never_uses_entry_ai_off_shortcut(self):
  self.own_v2()
  self.policy=RiskPolicy(max_order_notional=D("15"),
    max_total_exposure=D("75"),max_position_fraction=D(".5"),
    max_entries_per_day=2,max_exit_orders_per_day=3,ai_mode="OFF")
  out=self.engine(direction="BUY").run_once()
  self.assertEqual(out["state"],"V2_RISK_POLICY_UNVERIFIED")
  self.assertEqual(self.broker.posts,0)

 def test_signed_managed_cost_basis_required_before_sell_or_new_buy(self):
  self.own_v2()
  self.broker.held={"BTC-USD":D("1")}
  eng=self.engine(direction="SELL")
  eng.exit_evidence_provider=None
  out=eng.run_once()
  self.assertEqual(out["state"],"V2_EXIT_EVIDENCE_UNVERIFIED")
  self.assertEqual(self.broker.posts,0)

 def test_invalid_managed_lot_quantity_rejects_sell(self):
  self.own_v2()
  self.broker.held={"BTC-USD":D("1")}
  eng=self.engine(direction="SELL")
  eng.exit_evidence_provider=lambda symbol,account:ManagedExitLot(
    symbol,D("2"),D("2"),D("12"),
    self.now-timedelta(minutes=30),
    cost_basis_broker_verified=True,original_fills_reconciled=True)
  self.assertEqual(eng.run_once()["state"],"V2_EXIT_EVIDENCE_UNVERIFIED")
  self.assertEqual(self.broker.posts,0)

 def test_risk_reducing_stop_exit_with_stale_technical_bars(self):
  self.own_v2()
  self.broker.held={"BTC-USD":D("1")}
  out=self.engine(direction="SELL",gap=True).run_once()
  self.assertEqual(out["state"],"FILLED")
  self.assertEqual(self.broker.posts,1)

 def test_held_position_with_unknown_cost_blocks_new_entry(self):
  self.own_v2()
  self.broker.held={"BTC-USD":D("1")}
  eng=self.engine(direction="BUY")
  eng.exit_evidence_provider=lambda symbol,account:None
  self.assertEqual(eng.run_once()["state"],"V2_EXIT_EVIDENCE_UNVERIFIED")
  self.assertEqual(self.broker.posts,0)

 def test_missing_v1_daily_order_history_blocks_before_any_broker_post(self):
  self.own_v2()
  eng=self.engine();eng.v1_activity_provider=None
  status=eng.run_once()
  self.assertEqual(status["state"],"V2_V1_ACTIVITY_UNVERIFIED")
  self.assertEqual(self.broker.posts,0)

 def test_inherited_v1_entry_limit_prevents_migration_day_reset(self):
  self.own_v2()
  self.policy=RiskPolicy(max_order_notional=D("15"),
      max_total_exposure=D("75"),max_position_fraction=D(".5"),
      max_entries_per_day=1,max_exit_orders_per_day=3,ai_mode="REQUIRED")
  self.legacy=InheritedOrderLimits("robinhood_crypto","acct",1,0,
      frozenset(),False,True,True)
  result=self.engine().run_once()
  self.assertEqual(result["state"],"BLOCKED")
  self.assertEqual(result["reason"],"ENTRY_DAILY_COUNT_LIMIT")
  self.assertEqual(self.broker.posts,0)

 def test_inherited_reentry_cooldown_skips_new_buy(self):
  self.own_v2()
  self.legacy=InheritedOrderLimits("robinhood_crypto","acct",0,0,
      frozenset({"BTC-USD"}),False,True,True)
  result=self.engine().run_once()
  self.assertEqual(result["state"],"NO_VALIDATED_V2_SIGNAL")
  self.assertEqual(self.broker.posts,0)

 def test_v1_handover_wrong_account_cannot_authorize_order(self):
  self.own_v2()
  self.legacy=InheritedOrderLimits("robinhood_crypto","wrong-account",0,0,
      frozenset(),False,True,True)
  self.assertEqual(self.engine().run_once()["state"],"V2_V1_ACTIVITY_UNVERIFIED")
  self.assertEqual(self.broker.posts,0)

 def test_inherited_exits_still_limit_protective_sell(self):
  self.own_v2()
  self.broker.held={"BTC-USD":D("1")}
  self.policy=RiskPolicy(max_order_notional=D("15"),
      max_total_exposure=D("75"),max_position_fraction=D(".5"),
      max_entries_per_day=2,max_exit_orders_per_day=1,ai_mode="REQUIRED")
  self.legacy=InheritedOrderLimits("robinhood_crypto","acct",0,1,
      frozenset(),False,True,True)
  out=self.engine(direction="SELL").run_once()
  self.assertEqual(out["state"],"BLOCKED")
  self.assertEqual(out["reason"],"EXIT_ORDER_LIMIT")
  self.assertEqual(self.broker.posts,0)

 def test_valid_protective_sell_without_model_while_daily_entry_limit_spent(self):
  self.own_v2()
  self.broker.held={"BTC-USD":D("1")}
  eng=self.engine(direction="SELL");eng.reviewer=None
  out=eng.run_once()
  self.assertEqual(out["state"],"FILLED")
  self.assertEqual(self.broker.posts,1)
 def test_not_a_stale_quote_shortcut(self):
  self.own_v2()
  self.price=MarketSnapshot("BTC-USD",AssetClass.CRYPTO,"coinbase_public_paper",
    self.now-timedelta(seconds=2),self.now,D("10"),D("10.01"),D("10.005"),True)
  out=self.engine().run_once()
  self.assertEqual(out["state"],"BLOCKED")
  self.assertEqual(self.broker.posts,0)

if __name__=="__main__":main()
