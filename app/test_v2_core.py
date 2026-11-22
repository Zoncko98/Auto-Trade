"""Contract and recovery tests for the V2 foundation. ALL orders are virtual."""
import os,sqlite3,tempfile,threading,unittest
from pathlib import Path
from datetime import datetime,timezone,timedelta
from decimal import Decimal
from unittest.mock import patch
from trader_v2.models import (Account,AssetClass,AIState,AIReview,AuthState,
    Capability,Candle,Candidate,MarketSnapshot,OrderIntent,OrderSide,OrderState,
    RiskPolicy,RiskDecision,amount)
from trader_v2.store import EventStore,IntentConflict,IllegalTransition
from trader_v2.simulation import SimulatedBroker,SimulationRejected
from trader_v2.contracts import TradingBroker,inspect_paper_adapter
from trader_v2.risk import evaluate_risk
from trader_v2.strategies import StockController,CryptoController
from trader_v2.engine import PaperPipeline
from trader_v2.status import summary
from trader_v2.demo import run_demo

D=Decimal
class V2Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.journal=EventStore(self.root/"v2"/"events.sqlite3")
        self.sim=SimulatedBroker(self.root/"v2"/"simulation.sqlite3",fee_bps=D("5"))
        self.sim.seed("paper-a",AssetClass.STOCK,D("1000"))
        self.now=datetime.now(timezone.utc).replace(microsecond=0)
        self.market=MarketSnapshot("DEMO",AssetClass.STOCK,"test-feed",
          self.now,self.now,D("9.99"),D("10"),D("10"),True)
        self.sim.quote(self.market)
        self.policy=RiskPolicy(max_order_notional=D("100"),max_total_exposure=D("300"),
                              max_position_fraction=D("0.5"))
        self.buy=Candidate("stock_sma","1","paper-a","DEMO",AssetClass.STOCK,
            OrderSide.BUY,self.now,{"indicator":"synthetic-cross"})
    def execute(self,**kw):
        return PaperPipeline(self.sim,self.journal,**kw).evaluate(
            self.buy,self.market,self.policy,now=self.now)

class ModelContracts(unittest.TestCase):
    def test_decimal_rejects_float_boolean_nan_negative_and_overprecision(self):
        for x in (0.1,True,"NaN","Infinity","-1","1e-20"):
            with self.subTest(x=x),self.assertRaises(ValueError):
                amount(x)
    def test_quote_rejects_naive_timestamps_and_crossed_spreads(self):
        now=datetime.now(timezone.utc)
        with self.assertRaises(ValueError):
            MarketSnapshot("A",AssetClass.STOCK,"feed",now.replace(tzinfo=None),now,D("1"),D("2"),D("1"),True)
        with self.assertRaises(ValueError):
            MarketSnapshot("A",AssetClass.STOCK,"feed",now,now,D("3"),D("2"),D("2"),True)
    def test_account_rejects_unsupported_symbols_and_cash_over_equity(self):
        cap=Capability(frozenset({AssetClass.STOCK}))
        with self.assertRaises(ValueError):
            Account("id","paper",cap,D("200"),D("100"))
        with self.assertRaises(ValueError):
            Account("id","paper",cap,D("100"),D("100"),positions={"bad symbol":D("1")})
    def test_ai_review_expiry_not_before_creation(self):
        now=datetime.now(timezone.utc)
        with self.assertRaises(ValueError):
            AIReview(AIState.PASS,"DEMO",now,now-timedelta(seconds=1))

class StrategyContracts(unittest.TestCase):
    def sequence(self,closes,sym="DEMO"):
        now=datetime.now(timezone.utc).replace(microsecond=0)
        return [Candle(sym,now-timedelta(minutes=5*(len(closes)-1-i)),D(str(v)))
                for i,v in enumerate(closes)]
    def test_stock_buy_sell_and_no_signal_are_deterministic(self):
        ctrl=StockController()
        buy=ctrl.candidate("paper-a",self.sequence([10,10,9,8,8,14]))
        self.assertEqual(buy.side,OrderSide.BUY)
        self.assertEqual(buy.asset_class,AssetClass.STOCK)
        sell=ctrl.candidate("paper-a",self.sequence([10,10,12,14,14,4]))
        self.assertEqual(sell.side,OrderSide.SELL)
        self.assertIsNone(ctrl.candidate("paper-a",self.sequence([10]*6)))
        invalid=self.sequence([10,10,9,8,8,14])
        invalid[-1]=Candle("DEMO",invalid[-1].observed_at,invalid[-1].close,False)
        self.assertIsNone(ctrl.candidate("paper-a",invalid))
    def test_v2_live_stock_continuation_matches_v1_moderate_m5_trend(self):
        controller=StockController(include_continuation=True)
        rows=self.sequence([D("10"),D("10"),D("10"),
                            D("10.02"),D("10.06"),D("10.12")])
        # No completed 3/5 upward crossover is required for this separate
        # confirmed V1 continuation rule.
        result=controller.candidate("paper-a",rows)
        self.assertIsNotNone(result)
        self.assertEqual(result.side,OrderSide.BUY)
        self.assertEqual(result.evidence["indicator"],"M5_TREND_CONTINUATION")
        self.assertIsNone(StockController().candidate("paper-a",rows))
        steep=self.sequence([D("10"),D("10"),D("10"),
                             D("10.2"),D("10.5"),D("10.8")])
        self.assertIsNone(controller.candidate("paper-a",steep))

    def test_crypto_controller_is_separate_from_stock_periods(self):
        c=CryptoController()
        result=c.candidate("paper-crypto",self.sequence([10]*8+[20],"BTC-USD"))
        self.assertEqual(result.asset_class,AssetClass.CRYPTO)
        self.assertEqual(result.strategy,"crypto_sma")
        self.assertEqual(result.evidence["long_period"],"8")

class RiskContracts(V2Fixture):
    def test_unauthorized_or_disarmed_account_is_blocked(self):
        account=self.sim.account("paper-a")
        for auth,enabled in ((AuthState.REAUTH_REQUIRED,True),(AuthState.CONNECTED,False)):
            changed=Account(account.account_id,account.broker,account.capability,
                account.cash,account.equity,account.positions,auth,enabled,account.market_exposure)
            self.assertNotEqual(evaluate_risk(changed,self.buy,self.market,self.policy,
                                  now=self.now).code,"PASS")
    def test_stale_market_and_closed_market_block(self):
        s=self.market
        stale=MarketSnapshot("DEMO",AssetClass.STOCK,"test-feed",
            self.now-timedelta(minutes=10),self.now,D("9.99"),D("10"),D("10"),True)
        closed=MarketSnapshot("DEMO",AssetClass.STOCK,"test-feed",
            self.now,self.now,D("9.99"),D("10"),D("10"),False)
        for quote in (stale,closed):
            result=evaluate_risk(self.sim.account("paper-a"),self.buy,quote,self.policy,now=self.now)
            self.assertEqual(result.code,"ENTRY_BLOCKED")
    def test_preflight_enforces_order_budget_and_whole_share(self):
        result=evaluate_risk(self.sim.account("paper-a"),self.buy,self.market,
                             self.policy,now=self.now)
        self.assertEqual(result.code,"PASS")
        self.assertEqual(result.quantity,D("9"))
        self.assertLessEqual(result.quantity*result.limit_price,self.policy.max_order_notional)
        self.assertFalse(self.sim.account("paper-a").capability.fractional)
    def test_exit_is_evaluated_even_after_entry_count_and_daily_loss(self):
        self.execute()
        sell=Candidate("stock_sma","1","paper-a","DEMO",AssetClass.STOCK,
            OrderSide.SELL,self.now,{"indicator":"confirmed-cross-down"})
        policy=RiskPolicy(max_entries_per_day=1,max_daily_loss=D("1"),
                          max_exit_orders_per_day=2)
        result=evaluate_risk(self.sim.account("paper-a"),sell,self.market,policy,
                now=self.now,entries_today=100,daily_realized_loss=D("999"))
        self.assertEqual(result.code,"PASS")
        self.assertEqual(result.reason,"RISK_REDUCING_EXIT")
        exhausted=evaluate_risk(self.sim.account("paper-a"),sell,self.market,policy,
                now=self.now,entries_today=100,exits_today=2,daily_realized_loss=D("999"))
        self.assertEqual(exhausted.reason,"EXIT_ORDER_LIMIT")
    def test_robinhood_exit_respects_original_per_order_notional(self):
        from trader_v2.models import Capability
        cap=Capability(frozenset({AssetClass.CRYPTO}),fractional=True,
            min_notional=D("1"),quantity_increment=D("0.001"))
        account=Account("rh-a","robinhood_crypto",cap,D("0"),D("100"),
            {"BTC-USD":D("4")},AuthState.CONNECTED,True,D("40"))
        quote=MarketSnapshot("BTC-USD",AssetClass.CRYPTO,
            "robinhood_signed",self.now,self.now,D("10"),D("10.01"),D("10"),True)
        sell=Candidate("crypto_exit","compat-1","rh-a","BTC-USD",AssetClass.CRYPTO,
            OrderSide.SELL,self.now,{"reason":"STOP_LOSS"})
        policy=RiskPolicy(max_order_notional=D("15"),max_total_exposure=D("100"))
        result=evaluate_risk(account,sell,quote,policy,now=self.now)
        self.assertEqual(result.code,"PASS")
        self.assertEqual(result.quantity,D("1.5"))
        self.assertLessEqual(result.quantity*quote.bid,policy.max_order_notional)

    def test_no_holdings_cannot_short(self):
        sell=Candidate("stock_sma","1","paper-a","DEMO",AssetClass.STOCK,
            OrderSide.SELL,self.now,{"indicator":"confirmed-cross-down"})
        result=evaluate_risk(self.sim.account("paper-a"),sell,self.market,self.policy,now=self.now)
        self.assertEqual(result.reason,"NO_LONG_HOLDING")
    def test_account_limit_caps_spend(self):
        account=self.sim.account("paper-a")
        full=Account(account.account_id,account.broker,account.capability,
                     D("100"),D("100"),{},market_exposure=D("95"),trading_enabled=True)
        policy=RiskPolicy(max_total_exposure=D("90"))
        self.assertEqual(evaluate_risk(full,self.buy,self.market,policy,now=self.now).reason,
                         "CASH_OR_EXPOSURE_EXHAUSTED")

class EventStoreTests(V2Fixture):
    def intent(self,quantity=D("2"),key="test-intent"):
        return OrderIntent(key,"paper-a","stock_sma","DEMO",AssetClass.STOCK,
                           OrderSide.BUY,quantity,D("10.05"),self.now)
    def risk(self,quantity=D("2")):
        return RiskDecision("PASS","TEST_APPROVED",quantity,D("10.05"),D("100"))
    def test_wal_and_durable_lifecycle(self):
        order=self.intent()
        row=self.journal.prepare(order,self.risk())
        self.assertEqual(row["state"],"INTENT_PERSISTED")
        self.assertEqual([x["state"] for x in self.journal.events(order.key)],
             ["PROPOSED","RISK_APPROVED","INTENT_PERSISTED"])
        self.journal.transition(order.key,OrderState.SUBMITTING)
        with self.assertRaises(IllegalTransition):
            self.journal.transition(order.key,OrderState.FILLED)
        self.journal.transition(order.key,OrderState.BROKER_ACCEPTED)
        self.journal.transition(order.key,OrderState.FILLED)
        self.assertEqual(EventStore(self.journal.path).get(order.key)["state"],"FILLED")
        with sqlite3.connect(str(self.journal.path)) as conn:
            self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0].lower(),"wal")
    def test_idempotency_rejects_conflicting_fingerprint(self):
        self.journal.prepare(self.intent(),self.risk())
        with self.assertRaises(IntentConflict):
            self.journal.prepare(self.intent(D("3")),self.risk(D("3")))
        self.assertEqual(self.journal.summary()["intents"],1)
    def test_parallel_writers_are_serialized_and_idempotent(self):
        errors=[]
        def work():
            try:self.journal.prepare(self.intent(),self.risk())
            except Exception as error:errors.append(error)
        jobs=[threading.Thread(target=work) for i in range(10)]
        for j in jobs:j.start()
        for j in jobs:j.join()
        self.assertEqual(errors,[])
        self.assertEqual(self.journal.summary()["events"],3)
    def test_unknown_state_cannot_be_replayed_or_filled_without_ack(self):
        self.journal.prepare(self.intent(),self.risk())
        self.journal.transition("test-intent",OrderState.SUBMITTING)
        self.journal.transition("test-intent",OrderState.UNKNOWN_REQUIRES_RECONCILIATION)
        with self.assertRaises(IllegalTransition):
            self.journal.transition("test-intent",OrderState.SUBMITTING)
        self.assertEqual(len(self.journal.pending("paper-a")),1)
    def test_world_readable_database_is_rejected(self):
        os.chmod(self.journal.path,0o644)
        with self.assertRaises(PermissionError):
            EventStore(self.journal.path)

class SimulatedExecution(V2Fixture):
    def test_simulated_broker_matches_contract_and_does_not_reset_capital(self):
        self.assertTrue(isinstance(self.sim,TradingBroker))
        self.assertEqual(inspect_paper_adapter(self.sim,"paper-a").cash,D("1000"))
        self.assertFalse(self.sim.seed("paper-a",AssetClass.STOCK,D("999999")))
        self.assertEqual(self.sim.account("paper-a").cash,D("1000"))
    def test_full_paper_pipeline_reconciles_and_deduplicates(self):
        result=self.execute()
        self.assertEqual(result.code,"FILLED")
        second=self.execute()
        self.assertEqual(second.code,"FILLED")
        self.assertEqual(self.journal.summary()["intents"],1)
        self.assertEqual(self.journal.summary()["events"],6)
        self.assertEqual(self.sim.account("paper-a").positions["DEMO"],D("9"))
    def test_paper_sell_uses_same_pipeline(self):
        self.execute()
        sell=Candidate("stock_sma","1","paper-a","DEMO",AssetClass.STOCK,
            OrderSide.SELL,self.now,{"indicator":"confirmed-exit"})
        result=PaperPipeline(self.sim,self.journal).evaluate(sell,self.market,self.policy,
                    now=self.now,entries_today=100,daily_realized_loss=D("1000"))
        self.assertEqual(result.code,"FILLED")
        self.assertNotIn("DEMO",self.sim.account("paper-a").positions)
    def test_after_fill_network_timeout_is_reconciled_without_duplicate_order(self):
        original=self.sim.submit
        def after_fill(intent):
            original(intent)
            raise TimeoutError("Synthetic connection dropped after broker fill")
        with patch.object(self.sim,"submit",side_effect=after_fill):
            result=self.execute()
        self.assertEqual(result.code,"RECONCILIATION_REQUIRED")
        self.assertEqual(len(self.journal.pending("paper-a")),1)
        recovered=PaperPipeline(self.sim,self.journal).reconcile(result.intent_key)
        self.assertEqual(recovered.code,"FILLED")
        self.assertEqual(self.journal.summary()["intents"],1)
        self.assertEqual(self.sim.account("paper-a").positions["DEMO"],D("9"))
        self.assertEqual(self.execute().code,"FILLED")
    def test_unknown_submit_without_broker_ack_cannot_repost(self):
        with patch.object(self.sim,"submit",side_effect=TimeoutError("No ack")) as submit:
            result=self.execute()
            self.assertEqual(result.code,"RECONCILIATION_REQUIRED")
            again=self.execute()
            self.assertEqual(again.code,"RECONCILIATION_REQUIRED")
            submit.assert_called_once()
        self.assertEqual(self.sim.account("paper-a").cash,D("1000"))
    def test_required_ai_absent_blocks(self):
        policy=RiskPolicy(max_order_notional=D("100"),max_total_exposure=D("300"),
                          max_position_fraction=D("0.5"),ai_mode="REQUIRED")
        result=PaperPipeline(self.sim,self.journal).evaluate(self.buy,self.market,policy,now=self.now)
        self.assertEqual(result.reason,"AI_UNAVAILABLE")
        self.assertEqual(self.journal.summary()["intents"],0)
    def test_explicit_ai_veto_blocks_even_optional_mode(self):
        class Reviewer:
            def review(self,candidate,snapshot):
                return AIReview(AIState.VETO,candidate.symbol,self_now,
                    self_now+timedelta(minutes=1),model="test",reason="synthetic veto")
        self_now=self.now
        policy=RiskPolicy(max_order_notional=D("100"),max_total_exposure=D("300"),
                          max_position_fraction=D("0.5"),ai_mode="OPTIONAL")
        result=PaperPipeline(self.sim,self.journal,reviewer=Reviewer()).evaluate(
                self.buy,self.market,policy,now=self.now)
        self.assertEqual(result.reason,"AI_VETO")
    def test_required_review_wrong_symbol_blocks(self):
        class Reviewer:
            def review(self,candidate,snapshot):
                return AIReview(AIState.PASS,"OTHER",self_now,
                    self_now+timedelta(minutes=1))
        self_now=self.now
        policy=RiskPolicy(max_order_notional=D("100"),max_total_exposure=D("300"),
                          max_position_fraction=D("0.5"),ai_mode="REQUIRED")
        result=PaperPipeline(self.sim,self.journal,reviewer=Reviewer()).evaluate(
                 self.buy,self.market,policy,now=self.now)
        self.assertEqual(result.reason,"AI_UNAVAILABLE")
    def test_persistent_simulation_after_reopen(self):
        result=self.execute()
        reopened=SimulatedBroker(self.sim.path,fee_bps=D("5"))
        self.assertEqual(reopened.find_order(result.intent_key).state,"FILLED")
        self.assertEqual(reopened.account("paper-a").positions["DEMO"],D("9"))
    def test_paper_cannot_receive_real_broker_adapter(self):
        with self.assertRaises(TypeError):
            PaperPipeline(object(),self.journal)

class FlagAndDemoTests(unittest.TestCase):
    def test_disabled_status_does_not_initialize_database(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{"AUTO_TRADER_V2_ENABLED":"false"}):
            r=summary(folder)
            self.assertFalse(r["feature_enabled"])
            self.assertFalse(r["live_order_authority"])
            self.assertFalse((Path(folder)/"v2").exists())
    def test_flagged_demo_is_simulated_and_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ,{"AUTO_TRADER_V2_ENABLED":"false"}):
                with self.assertRaises(RuntimeError):run_demo(folder)
            with patch.dict(os.environ,{"AUTO_TRADER_V2_ENABLED":"true",
                                         "AUTO_TRADER_V2_LIVE":"true"}):
                first=run_demo(folder)
                second=run_demo(folder)
                self.assertEqual(first["result"],"FILLED")
                self.assertEqual(second["result"],"FILLED")
                self.assertEqual(first["virtual_cash"],second["virtual_cash"])
                self.assertEqual(first["event_store"]["intents"],1)
                self.assertEqual(summary(folder)["store"],"READY")
                self.assertFalse(summary(folder)["live_order_authority"])
if __name__=="__main__":unittest.main()
