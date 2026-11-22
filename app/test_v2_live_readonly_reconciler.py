"""V2 live order recovery: read-only broker GET, durable state, no duplicate POST."""
from datetime import datetime,timezone
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,main
from unittest.mock import patch
from trader_v2.live_readonly_reconciler import run_once,ReadOnlyReconcilePipeline
from trader_v2.models import AssetClass,OrderSide,OrderIntent,RiskDecision,OrderState
from trader_v2.store import EventStore
from trader_v2.robinhood_signed_receipts import client_id
import json

ACCOUNT="safe-acct"
KEY="v2_reconcile_one"

class SignedGetOnlyClient:
    def __init__(self):
        self.accounts=[{"account_number":ACCOUNT,"status":"active"}]
        self.rows=[]
        self.gets=0
        self.posts=0
    def list_accounts(self):
        self.gets+=1
        return self.accounts
    def orders(self,account):
        assert account==ACCOUNT
        self.gets+=1
        return self.rows

def filled():
    return {"client_order_id":client_id(KEY,ACCOUNT),
        "account_number":ACCOUNT,"id":"signed-order-001",
        "state":"filled","filled_asset_quantity":"0.1",
        "average_price":"10","fee_charged":"0.01"}

class LiveReadOnlyReconcilerTests(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        self.client=SignedGetOnlyClient()
    def create(self):
        path=self.base/"v2/events.sqlite3"
        store=EventStore(path)
        order=OrderIntent(KEY,ACCOUNT,"crypto_sma","BTC-USD",AssetClass.CRYPTO,
                          OrderSide.BUY,D("0.1"),D("10"),datetime.now(timezone.utc))
        risk=RiskDecision("PASS","approved risk",D("0.1"),D("10"),D("10"))
        store.prepare(order,risk)
        return store
    def scan(self,**kwargs):
        with patch("trader_v2.live_readonly_reconciler._policy_account",return_value=ACCOUNT):
            return run_once(self.base,signed_client=self.client,**kwargs)
    def test_no_existing_v2_journal_no_broker_get_and_no_new_event_store(self):
        result=self.scan()
        self.assertEqual(result["state"],"NO_V2_LIVE_ORDER_JOURNAL")
        self.assertFalse((self.base/"v2/events.sqlite3").exists())
        self.assertEqual(self.client.gets,0)
        self.assertEqual(result["orders_submitted"],0)
        self.assertEqual(result["live_v2_order_authority"],False)
    def test_unsent_intent_never_autosubmits_or_spoofs_signed_ack(self):
        store=self.create()
        result=self.scan()
        self.assertEqual(result["state"],"PRE_SUBMISSION_REVIEW_REQUIRED")
        self.assertEqual(store.get(KEY)["state"],"INTENT_PERSISTED")
        self.assertEqual(self.client.gets,0)
        self.assertEqual(result["review_only"],1)
    def test_signed_fill_reconciles_once_without_any_broker_post(self):
        store=self.create()
        store.transition(KEY,OrderState.SUBMITTING)
        self.client.rows=[filled()]
        first=self.scan()
        self.assertEqual(first["state"],"RECONCILED_READ_ONLY")
        self.assertEqual(first["reconciled_terminal"],1)
        self.assertEqual(store.get(KEY)["state"],"FILLED")
        again=self.scan()
        self.assertEqual(again["state"],"NO_UNRESOLVED_V2_INTENTS")
        self.assertEqual(self.client.gets,2)
        self.assertEqual(self.client.posts,0)
        doc=json.loads((self.base/"v2/live_reconciliation/robinhood_crypto.json").read_text())
        self.assertNotIn(ACCOUNT,str(doc))
        self.assertEqual(doc["orders_submitted"],0)
    def test_missing_signed_order_locks_uncertain_submit_for_manual_review(self):
        store=self.create()
        store.transition(KEY,OrderState.SUBMITTING)
        result=self.scan()
        self.assertEqual(result["state"],"RECONCILIATION_REQUIRES_BROKER_REVIEW")
        self.assertEqual(store.get(KEY)["state"],"UNKNOWN_REQUIRES_RECONCILIATION")
        result=self.scan()
        self.assertEqual(result["still_unresolved"],1)
        self.assertEqual(self.client.posts,0)
    def test_foreign_account_and_ambiguous_broker_account_block_get(self):
        store=self.create()
        store.transition(KEY,OrderState.SUBMITTING)
        with patch("trader_v2.live_readonly_reconciler._policy_account",return_value="different"):
            result=run_once(self.base,signed_client=self.client)
        self.assertEqual(result["state"],"ACCOUNT_OR_ORIGINAL_INTENT_UNVERIFIED")
        self.assertEqual(self.client.gets,0)
        self.client.accounts.append(self.client.accounts[0].copy())
        result=self.scan()
        self.assertEqual(result["state"],"SIGNED_ACCOUNT_READ_UNAVAILABLE")
        self.assertEqual(self.client.posts,0)
    def test_signed_receipt_missing_fee_does_not_mark_fill(self):
        store=self.create()
        store.transition(KEY,OrderState.SUBMITTING)
        self.client.rows=[{**filled(),"fee_charged":None}]
        result=self.scan()
        self.assertEqual(result["state"],"RECONCILIATION_REQUIRES_BROKER_REVIEW")
        self.assertEqual(store.get(KEY)["state"],"UNKNOWN_REQUIRES_RECONCILIATION")
    def test_fingerprint_tampering_with_same_crypto_asset_blocks_get(self):
        store=self.create()
        store.transition(KEY,OrderState.SUBMITTING)
        with store._connect() as db:
            doc=json.loads(store.get(KEY)["document"])
            doc["quantity"]="5"
            db.execute("UPDATE intents SET document=? WHERE key=?", (json.dumps(doc),KEY))
        row=self.scan()
        self.assertEqual(row["state"],"ACCOUNT_OR_ORIGINAL_INTENT_UNVERIFIED")
        self.assertEqual(self.client.gets,0)

    def test_invalid_fingerprint_or_cross_asset_never_contacts_broker(self):
        store=self.create()
        store.transition(KEY,OrderState.SUBMITTING)
        with store._connect() as db:
            doc=json.loads(store.get(KEY)["document"])
            doc["asset_class"]="STOCK"
            db.execute("UPDATE intents SET document=? WHERE key=?", (json.dumps(doc),KEY))
        result=self.scan()
        self.assertEqual(result["state"],"ACCOUNT_OR_ORIGINAL_INTENT_UNVERIFIED")
        self.assertEqual(self.client.gets,0)

if __name__=="__main__":
    main()
