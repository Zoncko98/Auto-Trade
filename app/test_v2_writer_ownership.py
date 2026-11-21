"""Cross-process owner safeguards: safe legacy default, no implicit V2 orders."""
import json,os,tempfile,threading,time,unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from trader_v2.writer_ownership import (
    WriterOwnershipError,account_writer_scope,inspect_ownership,_paths
)

class OwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
    def claim_fixture(self,broker,acct,owner="V2",generation="generation-one"):
        lock,path,digest=_paths(self.root,broker,acct)
        doc={"schema":1,"broker":broker,"account_digest":digest,
             "owner":owner,"generation":generation}
        path.write_text(json.dumps(doc));path.chmod(0o600)
        return path
    def test_default_owner_is_v1_and_live_v2_cannot_submit(self):
        with account_writer_scope(self.root,"robinhood_crypto","account-1",owner="V1"):
            pass
        with self.assertRaisesRegex(WriterOwnershipError,"OTHER_WRITER"):
            with account_writer_scope(self.root,"robinhood_crypto","account-1",
                                      owner="V2",generation="generation-one"):
                self.fail("V2 must not acquire unclaimed account")
        self.assertEqual(inspect_ownership(self.root,"robinhood_crypto","account-1")["owner"],"V1")
    def test_v2_owner_blocks_legacy_even_if_armed(self):
        self.claim_fixture("robinhood_crypto","account-1")
        with self.assertRaisesRegex(WriterOwnershipError,"OTHER_WRITER"):
            with account_writer_scope(self.root,"robinhood_crypto","account-1",owner="V1"):
                self.fail("V1 must never retain writer after transfer")
        with account_writer_scope(self.root,"robinhood_crypto","account-1",
                                  owner="V2",generation="generation-one"):
            pass
        with self.assertRaisesRegex(WriterOwnershipError,"GENERATION_MISMATCH"):
            with account_writer_scope(self.root,"robinhood_crypto","account-1",
                                      owner="V2",generation="old-generation"):
                self.fail()
    def test_multiple_accounts_independent(self):
        self.claim_fixture("webull","stock1")
        with account_writer_scope(self.root,"webull","stock2",owner="V1"):pass
        with account_writer_scope(self.root,"schwab","stock1",owner="V1"):pass
        with self.assertRaises(WriterOwnershipError):
            with account_writer_scope(self.root,"webull","stock1",owner="V1"):pass
    def test_invalid_owner_or_broker_rejected(self):
        for broker,account,owner in [
            ("unknown","abc","V1"),("schwab","", "V1"),
            ("schwab","secret/../../", "V1"),("schwab","safe", "ROOT"),
        ]:
            with self.subTest(broker=broker,account=account),self.assertRaises(WriterOwnershipError):
                with account_writer_scope(self.root,broker,account,owner=owner):pass
    def test_symlink_owner_file_not_treated_as_missing(self):
        _,path,_=_paths(self.root,"webull","one")
        target=path.with_suffix(".missing")
        path.symlink_to(target)
        with self.assertRaises(WriterOwnershipError):
            with account_writer_scope(self.root,"webull","one",owner="V1"):pass
    def test_exposed_or_corrupt_owner_denied(self):
        path=self.claim_fixture("schwab","one")
        path.chmod(0o644)
        with self.assertRaises(WriterOwnershipError):
            with account_writer_scope(self.root,"schwab","one",owner="V2",
                                      generation="generation-one"):pass
        path.chmod(0o600)
        path.write_text("{INVALID")
        with self.assertRaises(WriterOwnershipError):
            with account_writer_scope(self.root,"schwab","one",owner="V1"):pass
    def test_exclusive_lock_blocks_other_account_writer_on_same_account(self):
        first=threading.Event();release=threading.Event();entered=threading.Event()
        def hold():
            with account_writer_scope(self.root,"robinhood_crypto","abc",owner="V1"):
                first.set();release.wait(3)
        def wait():
            first.wait(3)
            with account_writer_scope(self.root,"robinhood_crypto","abc",owner="V1"):
                entered.set()
        with ThreadPoolExecutor(max_workers=2) as pool:
            a=pool.submit(hold);b=pool.submit(wait)
            self.assertTrue(first.wait(2))
            self.assertFalse(entered.wait(0.15))
            release.set();a.result(timeout=3);b.result(timeout=3)
            self.assertTrue(entered.is_set())
    def test_no_production_cutover_mutation_api(self):
        import trader_v2.writer_ownership as module
        self.assertFalse(hasattr(module,"set_owner"))
        self.assertFalse(hasattr(module,"stage_owner_for_tests_only"))

if __name__=="__main__":unittest.main()
