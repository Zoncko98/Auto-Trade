"""Durable account-scoped V1/V2 order writer transfer, not a cutover controller.

This primitive never performs a broker API call or changes a worker setting.
Its caller MUST independently obtain current signed broker/account/order/cash
proof, stop the affected writer, and explicitly authorize the account.
Nothing invokes transfer automatically; the default owner remains V1.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime,timezone,timedelta
from pathlib import Path
import fcntl,json,os,secrets,stat

from .models import utc
from .writer_ownership import (
    WriterOwnershipError,_paths,_private_read,GENERATION
)


@dataclass(frozen=True)
class TransferAttestation:
    broker: str
    account: str
    from_owner: str
    to_owner: str
    expected_generation: str | None
    checked_at: datetime
    expires_at: datetime
    operator_confirmed: bool
    old_worker_stopped: bool
    local_intents_resolved: bool
    signed_open_orders_resolved: bool
    signed_account_verified: bool
    signed_positions_verified: bool
    funding_and_settlement_verified: bool
    broker_session_verified: bool
    risk_policy_verified: bool
    replacement_worker_ready: bool

    def valid(self,broker,account,from_owner,to_owner,now):
        try:
            checked=utc(self.checked_at)
            expiry=utc(self.expires_at)
            moment=utc(now)
        except ValueError:
            return False
        if (self.broker!=broker or self.account!=account or
                self.from_owner!=from_owner or self.to_owner!=to_owner):
            return False
        if not (checked-timedelta(seconds=2)<=moment<=expiry and
                checked<=expiry<=checked+timedelta(seconds=120)):
            return False
        fields=("operator_confirmed","old_worker_stopped",
                "local_intents_resolved","signed_open_orders_resolved",
                "signed_account_verified","signed_positions_verified",
                "funding_and_settlement_verified","broker_session_verified",
                "risk_policy_verified","replacement_worker_ready")
        return all(type(getattr(self,k)) is bool and getattr(self,k) for k in fields)


def transfer_writer(root,broker,account,*,from_owner,to_owner,proof,now=None):
    """Atomic owner switch after independent external validations.

    Does NOT mint permission from user-input booleans. Only a trusted
    broker/supervisor integration should create and use a current attestation.
    Exposed neither as a public HTTP endpoint nor a default worker action.
    """
    if (from_owner,to_owner) not in (("V1","V2"),("V2","V1")):
        raise WriterOwnershipError("UNSUPPORTED_WRITER_TRANSFER_DIRECTION")
    now=utc(now or datetime.now(timezone.utc))
    if (not isinstance(proof,TransferAttestation) or
            not proof.valid(broker,account,from_owner,to_owner,now)):
        raise WriterOwnershipError("INDEPENDENT_HANDOFF_PROOF_NOT_VERIFIED")
    lock,record,digest=_paths(root,broker,account)
    fd=os.open(lock,os.O_CREAT|os.O_RDWR|getattr(os,"O_NOFOLLOW",0),0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode) or os.fstat(fd).st_mode & 0o077:
            raise WriterOwnershipError("WRITER_LOCK_UNSAFE")
        fcntl.flock(fd,fcntl.LOCK_EX)
        current=_private_read(record,digest,broker)
        if current["owner"]!=from_owner:
            raise WriterOwnershipError("WRITER_ALREADY_TRANSFERRED_OR_WRONG_OWNER")
        if current["generation"]!=proof.expected_generation:
            raise WriterOwnershipError("WRITER_STALE_GENERATION_EVIDENCE")
        generation=secrets.token_hex(16)
        if not GENERATION.fullmatch(generation):
            raise WriterOwnershipError("WRITER_GENERATION_INVALID")
        payload={"schema":1,"broker":broker,"account_digest":digest,
                 "owner":to_owner,"generation":generation,
                 "transferred_at":now.isoformat()}
        temp=record.parent/("."+record.name+"-"+secrets.token_hex(8)+".tmp")
        flags=os.O_CREAT|os.O_EXCL|os.O_WRONLY|getattr(os,"O_NOFOLLOW",0)
        try:
            f=os.open(temp,flags,0o600)
            with os.fdopen(f,"w",encoding="utf-8") as stream:
                json.dump(payload,stream,separators=(",",":"),sort_keys=True)
                stream.flush();os.fsync(stream.fileno())
            os.replace(temp,record)
            parentfd=os.open(record.parent,os.O_RDONLY)
            try:os.fsync(parentfd)
            finally:os.close(parentfd)
        finally:
            if temp.exists():temp.unlink()
        return {"broker":broker,"owner":to_owner,
                "generation":generation,"transferred_at":now.isoformat(),
                "requires_new_fresh_handoff_proof":True}
    finally:
        try:fcntl.flock(fd,fcntl.LOCK_UN)
        finally:os.close(fd)
