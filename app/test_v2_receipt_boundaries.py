"""No-network tests for fail-closed V2 broker receipt and fill boundaries."""
from __future__ import annotations
from datetime import datetime,timezone
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import patch
import tempfile
import unittest

from trader_v2.models import (
    AssetClass,Candidate,MarketSnapshot,OrderIntent,OrderSide,
    OrderState,RiskDecision,RiskPolicy
)
from trader_v2.contracts import BrokerExecution
from trader_v2.engine import PaperPipeline
from trader_v2.simulation import SimulatedBroker
from trader_v2.store import EventStore


class ReceiptBoundaries(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root=Path(temporary.name)
        self.store=EventStore(root/"journal.sqlite3")
        self.sim=SimulatedBroker(root/"sim.sqlite3")
        self.sim.seed("paper-abc",AssetClass.STOCK,D("1000"),fractional=True)
        self.pipe=PaperPipeline(self.sim,self.store)
        self.now=datetime.now(timezone.utc).replace(microsecond=0)
        self.intent=OrderIntent("v2_receipt_test","paper-abc","test","ABC",
            AssetClass.STOCK,OrderSide.BUY,D("2"),D("10.05"),self.now)
        self.decision=RiskDecision("PASS","TEST",D("2"),D("10.05"),D("30"))

    def staged(self):
        self.store.prepare(self.intent,self.decision)
        self.store.transition(self.intent.key,OrderState.SUBMITTING)

    def receipt(self, *, state="FILLED", order="SIM-ORDER-A", filled="2", price="10", fees="0.01"):
        return BrokerExecution(self.intent.key,state,order,D(filled),D(price),D(fees))

    def assert_unresolved(self, receipt, expected_reason):
        result=self.pipe._accept(self.intent.key,receipt)
        self.assertEqual(result.code,"RECONCILIATION_REQUIRED")
        self.assertEqual(result.reason,expected_reason)
        self.assertEqual(self.store.get(self.intent.key)["state"],"UNKNOWN_REQUIRES_RECONCILIATION")
        self.assertEqual(len(self.store.pending("paper-abc")),1)
        self.assertEqual(self.sim.account("paper-abc").cash,D("1000"))

    def test_wrong_total_fill_quantity_never_closes_intent(self):
        self.staged()
        self.assert_unresolved(self.receipt(filled="1"),"BROKER_FULL_FILL_QUANTITY_MISMATCH")

    def test_broker_overfill_never_closes_intent(self):
        self.staged()
        self.assert_unresolved(self.receipt(filled="3"),"BROKER_OVERFILL_UNVERIFIED")

    def test_fill_outside_original_limit_never_closes_intent(self):
        self.staged()
        self.assert_unresolved(self.receipt(price="10.06"),"BROKER_FILL_PRICE_VIOLATES_LIMIT")

    def test_accepted_state_cannot_claim_filled_shares(self):
        self.staged()
        self.assert_unresolved(self.receipt(state="BROKER_ACCEPTED",filled="2"),
                               "BROKER_ACCEPTED_WITH_UNREPORTED_FILL")

    def test_broker_order_identifier_cannot_change_after_ack(self):
        self.staged()
        result=self.pipe._accept(self.intent.key,self.receipt(
            state="BROKER_ACCEPTED",filled="0",price="0",fees="0"))
        self.assertEqual(result.code,"BROKER_ACCEPTED")
        self.assert_unresolved(self.receipt(order="SIM-ORDER-B"),"BROKER_ORDER_ID_CHANGED")

    def test_cumulative_partial_fills_cannot_regress(self):
        self.staged()
        self.assertEqual(self.pipe._accept(self.intent.key,self.receipt(
            state="PARTIALLY_FILLED",filled="1",price="10",fees="0.01")).code,
            "PARTIALLY_FILLED")
        self.assert_unresolved(self.receipt(
            state="PARTIALLY_FILLED",filled="0.5",price="10",fees="0.01"),
            "BROKER_CUMULATIVE_FILL_REGRESSION")

    def test_partial_cancel_preserves_cumulative_economics(self):
        self.staged()
        self.pipe._accept(self.intent.key,self.receipt(
            state="PARTIALLY_FILLED",filled="1",price="10",fees="0.01"))
        outcome=self.pipe._accept(self.intent.key,self.receipt(
            state="CANCELED",filled="1",price="10",fees="0.01"))
        self.assertEqual(outcome.code,"CANCELED")
        evidence=self.store.events(self.intent.key)[-1]["evidence"]
        self.assertEqual(evidence["filled_quantity"],"1")
        self.assertEqual(evidence["average_price"],"10")
        self.assertEqual(evidence["broker_order_id"],"SIM-ORDER-A")

    def test_valid_original_order_cumulative_receipt_is_accepted(self):
        self.staged()
        self.assertEqual(self.pipe._accept(self.intent.key,self.receipt()).code,"FILLED")
        self.assertEqual(self.store.summary()["unresolved"],0)

    def test_malformed_receipt_types_rejected_before_persistence(self):
        for qty in (-1,"NaN",1.3):
            with self.subTest(qty=qty),self.assertRaises(ValueError):
                BrokerExecution(self.intent.key,"FILLED","SIM-ONE",qty,D("10"),D("0"))
        with self.assertRaises(ValueError):
            self.receipt(state="COMPLETED")
        with self.assertRaises(ValueError):
            self.receipt(order="NOT A BROKER ID")

    def test_mismatched_receipt_does_not_retry_broker_submission(self):
        self.sim.quote(MarketSnapshot("ABC",AssetClass.STOCK,"test",
            self.now,self.now,D("9.99"),D("10"),D("10"),True))
        candidate=Candidate("test","1","paper-abc","ABC",AssetClass.STOCK,
            OrderSide.BUY,self.now,{"indicator":"synthetic"})
        # The adapter claims a full fill without matching the proposed size.
        bad=BrokerExecution("v2_bad","FILLED","SIM-ORDER",D("1"),D("10"),D("0"))
        with patch.object(self.sim,"submit",return_value=bad) as submit:
            first=self.pipe.evaluate(candidate,self.sim._quotes[("ABC",AssetClass.STOCK)],
                                    RiskPolicy(),now=self.now)
            again=self.pipe.evaluate(candidate,self.sim._quotes[("ABC",AssetClass.STOCK)],
                                    RiskPolicy(),now=self.now)
        self.assertEqual(first.code,"RECONCILIATION_REQUIRED")
        self.assertEqual(again.code,"RECONCILIATION_REQUIRED")
        self.assertEqual(submit.call_count,1)


if __name__=="__main__":
    unittest.main()
