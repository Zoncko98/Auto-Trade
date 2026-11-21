"""No-network per-account ownership transfer and rollback tests."""
from dataclasses import replace
from datetime import datetime,timezone,timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,main

from trader_v2.writer_transfer import TransferAttestation,transfer_writer
from trader_v2.writer_ownership import (
    account_writer_scope,inspect_ownership,WriterOwnershipError
)

class V2WriterTransferTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.now=datetime.now(timezone.utc).replace(microsecond=0)
        self.broker="robinhood_crypto"
        self.account="account_production_123"

    def proof(self,from_owner="V1",to_owner="V2",gen=None,**changes):
        data=dict(broker=self.broker,account=self.account,
            from_owner=from_owner,to_owner=to_owner,
            expected_generation=gen,
            checked_at=self.now,expires_at=self.now+timedelta(seconds=60),
            operator_confirmed=True,old_worker_stopped=True,
            local_intents_resolved=True,signed_open_orders_resolved=True,
            signed_account_verified=True,signed_positions_verified=True,
            funding_and_settlement_verified=True,broker_session_verified=True,
            risk_policy_verified=True,replacement_worker_ready=True)
        data.update(changes)
        return TransferAttestation(**data)

    def test_no_proof_no_change_no_second_writer(self):
        with self.assertRaises(WriterOwnershipError):
            transfer_writer(self.root,self.broker,self.account,
                from_owner="V1",to_owner="V2",proof=None,now=self.now)
        with account_writer_scope(self.root,self.broker,self.account,owner="V1"):
            pass
        self.assertEqual(inspect_ownership(self.root,self.broker,self.account)["owner"],"V1")

    def test_verified_atomic_transfer_blocks_v1_and_allows_only_correct_generation(self):
        result=transfer_writer(self.root,self.broker,self.account,
              from_owner="V1",to_owner="V2",proof=self.proof(),now=self.now)
        generation=result["generation"]
        self.assertEqual(len(generation),32)
        with self.assertRaises(WriterOwnershipError):
            with account_writer_scope(self.root,self.broker,self.account,owner="V1"):
                pass
        with self.assertRaises(WriterOwnershipError):
            with account_writer_scope(self.root,self.broker,self.account,
                    owner="V2",generation="a"*32):
                pass
        with account_writer_scope(self.root,self.broker,self.account,
                owner="V2",generation=generation):
            pass
        records=list((self.root/"v2"/"writer_ownership").glob("*.json"))
        self.assertEqual(len(records),1)
        self.assertEqual(records[0].stat().st_mode&0o077,0)
        self.assertNotIn(self.account,records[0].read_text())

    def test_rollback_requires_fresh_proof_for_exact_v2_generation(self):
        result=transfer_writer(self.root,self.broker,self.account,
              from_owner="V1",to_owner="V2",proof=self.proof(),now=self.now)
        gen=result["generation"]
        with self.assertRaises(WriterOwnershipError):
            transfer_writer(self.root,self.broker,self.account,
                from_owner="V2",to_owner="V1",
                proof=self.proof("V2","V1",gen="f"*32),now=self.now)
        returned=transfer_writer(self.root,self.broker,self.account,
              from_owner="V2",to_owner="V1",
              proof=self.proof("V2","V1",gen=gen),now=self.now)
        with account_writer_scope(self.root,self.broker,self.account,owner="V1"):
            pass
        self.assertEqual(returned["owner"],"V1")
        with self.assertRaises(WriterOwnershipError):
            with account_writer_scope(self.root,self.broker,self.account,
                                     owner="V2",generation=gen):
                pass
        # Future handoff must include previous V1 generation, avoiding stale
        # authorization from a prior rollout attempt.
        with self.assertRaises(WriterOwnershipError):
            transfer_writer(self.root,self.broker,self.account,
                from_owner="V1",to_owner="V2",proof=self.proof(),now=self.now)
        fresh=transfer_writer(self.root,self.broker,self.account,
             from_owner="V1",to_owner="V2",
             proof=self.proof(gen=returned["generation"]),now=self.now)
        self.assertEqual(fresh["owner"],"V2")

    def test_stale_wrong_account_missing_gate_or_boolean_as_string_refused(self):
        for bad in (
            self.proof(broker="schwab"),
            self.proof(account="different"),
            self.proof(operator_confirmed=False),
            self.proof(old_worker_stopped=False),
            self.proof(broker_session_verified=False),
            self.proof(funding_and_settlement_verified=False),
            self.proof(risk_policy_verified="true"),
            self.proof(checked_at=self.now-timedelta(seconds=180),
                       expires_at=self.now-timedelta(seconds=120)),
            self.proof(expires_at=self.now+timedelta(minutes=5)),
        ):
            with self.subTest(bad=bad),self.assertRaises(WriterOwnershipError):
                transfer_writer(self.root,self.broker,self.account,
                    from_owner="V1",to_owner="V2",proof=bad,now=self.now)
        self.assertEqual(inspect_ownership(self.root,self.broker,self.account)["owner"],"V1")

    def test_direction_and_owner_identity_must_match_attestation(self):
        with self.assertRaises(WriterOwnershipError):
            transfer_writer(self.root,self.broker,self.account,
                from_owner="V2",to_owner="V1",proof=self.proof(),now=self.now)
        with self.assertRaises(WriterOwnershipError):
            transfer_writer(self.root,self.broker,self.account,
                from_owner="V1",to_owner="V1",proof=self.proof(),now=self.now)

if __name__=="__main__":main()
