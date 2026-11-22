"""Actual V1->V2 Robinhood cutover under original account writer lock.

User-approved via a private container environment switch, never from a GET
endpoint. Stops exactly one original V1 process. All brokerage observations
are authenticated GETs; POSTs remain in the independently gated V2 scanner.
"""
from __future__ import annotations
from datetime import datetime,timezone,timedelta
from pathlib import Path
from hashlib import sha256
import stat

from .models import utc
from .writer_ownership import account_writer_scope,inspect_ownership
from .writer_transfer import TransferAttestation,transfer_writer
from .launch_gates import launch_status
from .v1_order_inheritance import read_inherited
from .conservative_risk_map import mapping
from .live_executor import SIGNED_GATES,public_status as executor_status
from .recorded_replay import _atomic_json
from .trusted_crypto_live import (signed_v1_worker_stopped,v1_inventory,
   verified_robinhood_parity,closed_crypto_bars)

class CutoverBlocked(ValueError):
    def __init__(self,code):
        self.code=code
        super().__init__(code)

def _require(ok,code):
    if ok is not True:raise CutoverBlocked(code)

def _root_private(root):
    root=Path(root);v2=root/"v2";target=v2/"cutover_robinhood"
    if v2.is_symlink() or target.is_symlink():
        raise CutoverBlocked("CUTOVER_PRIVATE_PATH_UNSAFE")
    for p in (v2,target):
        p.mkdir(mode=0o700,exist_ok=True)
        st=p.stat()
        if not stat.S_ISDIR(st.st_mode) or st.st_mode & 0o077:
            raise CutoverBlocked("CUTOVER_PRIVATE_DIR_UNSAFE")
    return target

def _redacted(root,state,reason):
    out={"schema":1,"checked_at":datetime.now(timezone.utc).isoformat(),
         "broker":"robinhood_crypto","state":state,"reason":reason}
    _atomic_json(_root_private(root)/"health.json",out)
    return out

def _check_signed(root,account,*,refresh,now):
    """Read all 10 actual signed gates; never rely on user-written booleans."""
    if refresh:
        from .migration_probe import run_once
        from .public_crypto import fetch_ticker
        report=run_once(root,public_feed=fetch_ticker)
        _require(report.get("account_verified") is True,"SIGNED_ACCOUNT_UNAVAILABLE")
    status=launch_status(root,"robinhood_crypto",now=now)
    gates={g["name"] for g in status["gates"] if g.get("verified") is True}
    _require(SIGNED_GATES.issubset(gates),"FRESH_BROKER_CUTOVER_GATES_INCOMPLETE")
    inherited=read_inherited(root,"robinhood_crypto",account,now=now)
    _require(inherited.signed_broker_history_fresh and
             inherited.local_journal_terminal,"LEGACY_SIGNED_ORDER_HISTORY_NOT_RECONCILED")
    return status,inherited

def _preflight(root,account):
    from robinhood_policy import read_policy
    from .v1_managed_lots import legacy_exit_policy
    from .live_position_projection import reconstruct
    from .ai_service import SharedAIReviewer
    from .ollama_transport import OllamaReviewTransport
    from .robinhood_live_adapter import RobinhoodLiveAdapter
    from robinhood_crypto_gateway import RobinhoodCryptoAdapter
    from .public_crypto import fetch_ticker
    from .autonomous_live import accepted_bars
    from unified_config import settings
    policy=read_policy(root)
    _require(policy.get("enabled") is True and policy.get("account")==account,
             "OPERATOR_ACCOUNT_NOT_ARMED")
    _require(mapping(root,"robinhood_crypto").get("state")==
             "SAVED_V1_NUMERIC_LIMITS_VALIDATED","ORIGINAL_RISK_POLICY_UNVERIFIED")
    _require(legacy_exit_policy(root,"robinhood_crypto",account).broker==
             "robinhood_crypto","ORIGINAL_EXIT_POLICY_UNVERIFIED")
    _require(len(v1_inventory(root,account))==0,"LEGACY_MANAGED_LOTS_REQUIRE_ADOPTION")
    v2events=Path(root)/"v2/events.sqlite3"
    if v2events.exists():
        doc=reconstruct(root,account)
        _require(doc.get("state")=="RECONCILED" and
                 doc.get("unresolved_intents")==0,
                 "V2_UNRESOLVED_ORDER_RECONCILIATION_REQUIRED")
    cfg=settings(root)
    model=cfg.get("ai_model");endpoint=cfg.get("ollama_url")
    SharedAIReviewer(OllamaReviewTransport(endpoint,model),model=model,
       timeout_seconds=18,ttl_seconds=45)
    now=datetime.now(timezone.utc)
    eligible=[]
    client=RobinhoodCryptoAdapter.from_state(root)
    for pair in ("BTC-USD","ETH-USD"):
        try:
            reading=RobinhoodLiveAdapter(client,account,policy,pair,
              verified_managed_positions={},public_trade_feed=fetch_ticker)
            profile=reading.account(account)
            _require(profile.account_id==account and
                     profile.trading_enabled,"LIVE_ACCOUNT_READ_UNVERIFIED")
            quote=reading.quote()
            candles=accepted_bars(closed_crypto_bars(root,pair,now=now),
                                  pair,quote.asset_class,now)
            if candles:
                eligible.append(pair)
        except Exception:
            continue
    _require(bool(eligible),"NO_REAL_SIGNED_QUOTE_AND_CLOSED_BARS")
    return eligible

def attempt(root,*,stop_v1,live_worker_ready,operator_approved,
            approved_account_digest=None):
    """Parent runtime invokes once per backoff when approved in compose env.

    The original V1 process stays active unless all pre-stop reads pass.
    After an in-flight V1 account lock drains, stop the V1 process and
    rescan signed broker status before atomically transferring ownership.
    Failure before transfer leaves owner V1; parent restarts V1 normally.
    """
    root=Path(root)
    from robinhood_policy import read_policy
    try:
        _require(operator_approved is True,"EXPLICIT_CUTOVER_APPROVAL_REQUIRED")
        policy=read_policy(root)
        account=policy.get("account")
        _require(isinstance(account,str) and bool(account) and
                 policy.get("enabled") is True,"ORIGINAL_ACCOUNT_NOT_ARMED")
        expected=sha256(("robinhood_crypto|"+account).encode()).hexdigest()
        _require(isinstance(approved_account_digest,str) and
                 approved_account_digest==expected,
                 "CUTOVER_APPROVED_ACCOUNT_NOT_SELECTED")
        owner=inspect_ownership(root,"robinhood_crypto",account)
        if owner.get("owner")=="V2":
            return _redacted(root,"TRANSFERRED","V2_ALREADY_EXCLUSIVE_OWNER")
        _require(owner.get("owner")=="V1","WRITER_OWNER_UNVERIFIED")
        _require(live_worker_ready is True,"V2_COORDINATOR_NOT_RUNNING")
        _require(executor_status(root).get("registered") is True,
                 "V2_COORDINATOR_HEARTBEAT_NOT_VERIFIED")
        _check_signed(root,account,refresh=True,now=datetime.now(timezone.utc))
        _preflight(root,account)
        # Acquire the ORIGINAL V1 broker order writer lock to let any
        # already-started POST finish before asking the child to stop.
        with account_writer_scope(root,"robinhood_crypto",account,owner="V1") as locked:
            _require(locked.get("generation")==owner.get("generation"),
                     "V1_OWNER_GENERATION_CHANGED")
            stop_v1()
            _require(signed_v1_worker_stopped(),"ORIGINAL_V1_WRITER_STILL_RUNNING")
        # The parent will NOT respawn V1 between this point and the owner
        # transfer, since this attempt runs in the same supervisor loop.
        after=datetime.now(timezone.utc)
        _check_signed(root,account,refresh=True,now=after)
        _preflight(root,account)
        _require(signed_v1_worker_stopped(),"ORIGINAL_WRITER_RESTARTED")
        _require(inspect_ownership(root,"robinhood_crypto",account)==owner,
                 "WRITER_GENERATION_CHANGED_BEFORE_TRANSFER")
        now=datetime.now(timezone.utc)
        report=launch_status(root,"robinhood_crypto",now=now)
        gates={g["name"] for g in report["gates"] if g["verified"]}
        _require(SIGNED_GATES.issubset(gates),"SIGNED_CUTOVER_PREFLIGHT_EXPIRED")
        _require(live_worker_ready is True,"REPLACEMENT_PROCESS_UNAVAILABLE")
        evidence=TransferAttestation(
            "robinhood_crypto",account,"V1","V2",owner.get("generation"),
            now,now+timedelta(seconds=75),True,True,True,True,True,
            True,True,True,True,True)
        result=transfer_writer(root,"robinhood_crypto",account,
          from_owner="V1",to_owner="V2",proof=evidence,now=now)
        _require(result.get("owner")=="V2","TRANSFER_NOT_CONFIRMED")
        return _redacted(root,"TRANSFERRED","V2_WRITER_OWNERSHIP_TRANSFERRED")
    except Exception as exc:
        # Never include exception text; it may contain signed broker data.
        reason=(exc.code if isinstance(exc,CutoverBlocked) else
                "SIGNED_CUTOVER_VALIDATION_UNAVAILABLE")
        return _redacted(root,"BLOCKED",reason)
