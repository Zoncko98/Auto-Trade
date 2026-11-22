"""V2 AI service contract tests; no broker orders or network calls."""
import json
import unittest
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from trader_v2.ai_service import SharedAIReviewer, ReviewUnavailable
from trader_v2.models import Candidate, MarketSnapshot, AssetClass, OrderSide, AIState

class SharedAIReviewerTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 21, tzinfo=timezone.utc)
        self.c = Candidate("stock_sma", "1", "paper-a", "DEMO", AssetClass.STOCK,
                           OrderSide.BUY, self.now, {"signal": "cross"})
        self.q = MarketSnapshot("DEMO", AssetClass.STOCK, "testfeed", self.now,
                                self.now, Decimal("10"), Decimal("10.01"),
                                Decimal("10"), True)
        self.calls = []
    def service(self, reply=None, **kwargs):
        def transport(prompt, timeout):
            self.calls.append((json.loads(prompt), timeout))
            return reply if reply is not None else json.dumps(
                {"symbol": "DEMO", "state": "PASS", "reason": "qualified"})
        return SharedAIReviewer(transport, model="mock", clock=lambda: self.now, **kwargs)
    def test_pass_and_cache(self):
        s = self.service()
        self.assertEqual(s.review(self.c, self.q).state, AIState.PASS)
        self.assertEqual(s.review(self.c, self.q).state, AIState.PASS)
        self.assertEqual(len(self.calls), 1)
    def test_veto(self):
        s = self.service('{"symbol":"DEMO","state":"VETO","reason":"negative catalyst"}')
        self.assertEqual(s.review(self.c, self.q).state, AIState.VETO)
    def test_malformed_or_wrong_symbol_fail_closed(self):
        for bad in ('not json','{"symbol":"WRONG","state":"PASS","reason":"ok"}',
                    '{"symbol":"DEMO","state":"PASS","reason":"ok","extra":1}',
                    '{"symbol":"DEMO","state":"UNKNOWN","reason":"ok"}'):
            with self.subTest(bad=bad), self.assertRaises(ReviewUnavailable):
                self.service(bad).review(self.c, self.q)
    def test_stale_quote_and_mismatched_quote(self):
        stale = MarketSnapshot("DEMO", AssetClass.STOCK, "testfeed",
            self.now - timedelta(seconds=91), self.now - timedelta(seconds=91),
            Decimal("10"), Decimal("10.01"), Decimal("10"), True)
        with self.assertRaises(ReviewUnavailable):
            self.service().review(self.c, stale)
        other = MarketSnapshot("OTHER", AssetClass.STOCK, "testfeed", self.now,
            self.now, Decimal("10"), Decimal("10.01"), Decimal("10"), True)
        with self.assertRaises(ReviewUnavailable):
            self.service().review(self.c, other)
        self.assertEqual(self.calls, [])
    def test_transport_exception_is_unavailable(self):
        def broken(*args): raise TimeoutError()
        with self.assertRaises(ReviewUnavailable):
            SharedAIReviewer(broken, model="mock", clock=lambda:self.now).review(self.c,self.q)
    def test_model_cannot_supply_own_expiry(self):
        s=self.service()
        result=s.review(self.c,self.q)
        self.assertEqual(result.expires_at, self.now+timedelta(seconds=60))
    def test_default_timeout_supports_verified_local_model_latency(self):
        s=self.service()
        self.assertGreaterEqual(s.timeout_seconds,15)
        self.assertLessEqual(s.timeout_seconds,30)
        result=s.review(self.c,self.q)
        self.assertEqual(result.state,AIState.PASS)
        self.assertEqual(self.calls[0][1],s.timeout_seconds)

    def test_timeout_and_ttl_are_bounded(self):
        with self.assertRaises(ValueError): self.service(timeout_seconds=200)
        with self.assertRaises(ValueError): self.service(ttl_seconds=600)
    def test_pipeline_ai_pass_veto_and_malformed_are_distinct(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from trader_v2.simulation import SimulatedBroker
        from trader_v2.store import EventStore
        from trader_v2.engine import PaperPipeline
        from trader_v2.models import RiskPolicy
        policy = RiskPolicy(ai_mode="REQUIRED", max_order_notional=Decimal("100"),
                            max_total_exposure=Decimal("300"), max_position_fraction=Decimal("0.5"))
        def run(reply):
            with TemporaryDirectory() as folder:
                base = Path(folder)
                sim = SimulatedBroker(base/"sim.sqlite3", clock=lambda:self.now)
                sim.seed("paper-a", AssetClass.STOCK, Decimal("1000"))
                sim.quote(self.q)
                engine = PaperPipeline(sim, EventStore(base/"events.sqlite3"),
                                       reviewer=self.service(reply))
                result = engine.evaluate(self.c, self.q, policy, now=self.now)
                return result, sim.account("paper-a")
        yes, account = run('{"symbol":"DEMO","state":"PASS","reason":"qualified"}')
        self.assertEqual(yes.code, "FILLED")
        self.assertGreater(account.positions.get("DEMO", Decimal("0")), 0)
        no, account = run('{"symbol":"DEMO","state":"VETO","reason":"negative catalyst"}')
        self.assertEqual((no.code,no.reason), ("BLOCKED","AI_VETO"))
        self.assertEqual(account.positions, {})
        unavailable, account = run("not json")
        self.assertEqual((unavailable.code,unavailable.reason),("BLOCKED","AI_UNAVAILABLE"))
        self.assertEqual(account.positions, {})
