"""V2 Robinhood historic-order reconciler. GET-only; no live submit path.

Never repairs a missing V2 order by resubmitting. Reconciles a persisted
SUBMITTING/ACCEPTED/PARTIAL/UNKNOWN intent using only a signed broker lookup,
the canonical exact-order receipt validator and the durable V2 journal.
"""
from __future__ import annotations
from datetime import datetime,timezone
from pathlib import Path
from .models import OrderState,utc
from .store import EventStore
from .engine import PaperPipeline
from .robinhood_signed_receipts import RobinhoodReadOnlyReceiptAdapter
from .recorded_replay import _atomic_json
from .readonly_adapters import private_json
import argparse,hashlib,json,os,stat

TO_LOOKUP=frozenset({
    OrderState.SUBMITTING.value,OrderState.BROKER_ACCEPTED.value,
    OrderState.PARTIALLY_FILLED.value,OrderState.UNKNOWN_REQUIRES_RECONCILIATION.value})
MAX_BATCH=6

class ReadOnlyReconcilePipeline(PaperPipeline):
    def __init__(self,broker,store):
        if not isinstance(broker,RobinhoodReadOnlyReceiptAdapter):
            raise TypeError("Signed GET-only receipt broker required")
        if not isinstance(store,EventStore):
            raise TypeError("Durable V2 event journal required")
        self.broker=broker
        self.store=store
        self.reviewer=None

def _private_dir(path):
    if path.is_symlink() or path.parent.is_symlink():
        raise PermissionError("RECONCILER_DIRECTORY_SYMLINK")
    path.parent.mkdir(parents=True,mode=0o700,exist_ok=True)
    if path.parent.stat().st_mode&0o077:
        raise PermissionError("RECONCILER_PARENT_DIRECTORY_UNSAFE")
    path.mkdir(mode=0o700,exist_ok=True)
    mode=path.stat().st_mode
    if not stat.S_ISDIR(mode) or mode&0o077:
        raise PermissionError("RECONCILER_DIRECTORY_UNSAFE")

def _policy_account(state):
    from robinhood_policy import read_policy
    doc=read_policy(state)
    ref=doc.get("account") if isinstance(doc,dict) else None
    from robinhood_crypto_gateway import ACCOUNT
    if not isinstance(ref,str) or ACCOUNT.fullmatch(ref) is None:
        return None
    return ref

def _valid_intent(item,account):
    if not isinstance(item,dict) or item.get("account_id")!=account:
        return False
    try:
        data=json.loads(item["document"])
    except (ValueError,TypeError,KeyError):
        return False
    return (hashlib.sha256(item["document"].encode()).hexdigest()==item.get("fingerprint")
        and isinstance(data,dict) and data.get("key")==item.get("key")
        and data.get("account_id")==account and data.get("asset_class")=="CRYPTO"
        and data.get("side") in ("BUY","SELL")
        and item.get("state") in TO_LOOKUP|frozenset((
            OrderState.INTENT_PERSISTED.value,
            OrderState.PROPOSED.value,OrderState.RISK_APPROVED.value)))

def run_once(state_dir,*,signed_client=None,now=None):
    now=utc(now or datetime.now(timezone.utc))
    base=Path(state_dir)
    target=base/"v2"/"live_reconciliation"
    _private_dir(target)
    doc={"schema":1,"broker":"robinhood_crypto","checked_at":now.isoformat(),
        "mode":"SIGNED_GET_ONLY_NO_ORDER_SUBMISSIONS","live_v2_order_authority":False,
        "orders_submitted":0,"pending_before":None,"review_only":0,
        "signed_receipts_checked":0,"reconciled_terminal":0,
        "still_unresolved":None,"first_blocker":"V2_INTENT_JOURNAL_UNVERIFIED"}
    def finish():
        _atomic_json(target/"robinhood_crypto.json",doc)
        return doc
    journal_path=base/"v2"/"events.sqlite3"
    if journal_path.is_symlink() or not journal_path.is_file():
        doc.update(state="NO_V2_LIVE_ORDER_JOURNAL",
                   pending_before=0,still_unresolved=0,
                   first_blocker="V2_LIVE_NOT_STARTED")
        return finish()
    if journal_path.stat().st_mode&0o077:
        doc.update(state="V2_JOURNAL_PERMISSIONS_UNVERIFIED")
        return finish()
    try:
        store=EventStore(journal_path)
        pending=store.pending()
    except Exception:
        doc.update(state="V2_JOURNAL_UNAVAILABLE")
        return finish()
    doc["pending_before"]=len(pending)
    if not pending:
        doc.update(state="NO_UNRESOLVED_V2_INTENTS",still_unresolved=0,
                   first_blocker="V2_LIVE_NOT_STARTED_OR_NO_OPEN_ORDERS")
        return finish()
    if len(pending)>MAX_BATCH:
        doc.update(state="TOO_MANY_PENDING_V2_INTENTS",
                   still_unresolved=len(pending),first_blocker="MANUAL_RECONCILIATION_REQUIRED")
        return finish()
    try: account=_policy_account(base)
    except Exception:account=None
    if not account or not all(_valid_intent(item,account) for item in pending):
        doc.update(state="ACCOUNT_OR_ORIGINAL_INTENT_UNVERIFIED",
                   still_unresolved=len(pending),first_blocker="MANUAL_RECONCILIATION_REQUIRED")
        return finish()
    to_check=[item for item in pending if item["state"] in TO_LOOKUP]
    doc["review_only"]=len(pending)-len(to_check)
    if not to_check:
        doc.update(state="PRE_SUBMISSION_REVIEW_REQUIRED",
                   still_unresolved=len(pending),first_blocker="INTENTS_NOT_SENT_NO_AUTOMATIC_RETRY")
        return finish()
    try:
        if signed_client is None:
            from robinhood_crypto_gateway import RobinhoodCryptoAdapter
            signed_client=RobinhoodCryptoAdapter.from_state(base)
        rows=signed_client.list_accounts()
        if not isinstance(rows,list) or sum(
            isinstance(row,dict) and row.get("account_number")==account
            and row.get("status")=="active" for row in rows)!=1:
            raise ValueError("Signed account selection not verified")
    except Exception:
        doc.update(state="SIGNED_ACCOUNT_READ_UNAVAILABLE",
                   still_unresolved=len(pending),first_blocker="SIGNED_BROKER_ACCOUNT_REQUIRED")
        return finish()
    pipeline=ReadOnlyReconcilePipeline(
        RobinhoodReadOnlyReceiptAdapter(signed_client,account),store)
    for item in to_check:
        doc["signed_receipts_checked"]+=1
        try:
            result=pipeline.reconcile(item["key"])
            if result.code in ("FILLED","CANCELED","REJECTED"):
                doc["reconciled_terminal"]+=1
        except Exception:
            # No details from broker exception; no retry of any POST.
            break
    try:doc["still_unresolved"]=len(store.pending())
    except Exception:doc["still_unresolved"]=len(pending)
    doc["state"]=("RECONCILED_READ_ONLY" if doc["still_unresolved"]==0
                 else "RECONCILIATION_REQUIRES_BROKER_REVIEW")
    doc["first_blocker"]=(None if doc["still_unresolved"]==0
                 else "PENDING_INTENTS_REQUIRE_SIGNED_BROKER_CONFIRMATION")
    return finish()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--state-dir",default=os.environ.get("STATE_DIR","/state"))
    args=parser.parse_args()
    result=run_once(args.state_dir)
    print("V2 signed no-POST reconciliation:",result["state"],flush=True)

if __name__=="__main__":
    main()
