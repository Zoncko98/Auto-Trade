"""Cross-process, per-account order-writer ownership and exclusion.

The original V1 writer owns a broker account by default. A future controlled
handoff must atomically move ownership only after every account-specific V1
order and external broker open order is reconciled. V1 and V2 order POSTs
serialize on the same account lock and recheck ownership under that lock.
No method in this module automatically arms an account or broker.
"""
from __future__ import annotations
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime,timezone
import fcntl,hashlib,json,os,re,stat,tempfile

BROKERS=frozenset(("schwab","webull","robinhood_crypto"))
ACCOUNT=re.compile(r"^[A-Za-z0-9._:/+=-]{1,128}$")
GENERATION=re.compile(r"^[A-Za-z0-9_-]{8,128}$")
class WriterOwnershipError(RuntimeError):pass

def _folder(root):
    parent=Path(root)/"v2"
    base=parent/"writer_ownership"
    for path in (parent,base):
        if path.is_symlink():
            raise WriterOwnershipError("WRITER_DIRECTORY_SYMLINK")
        try:path.mkdir(mode=0o700,exist_ok=True)
        except (OSError,ValueError,TypeError):
            raise WriterOwnershipError("WRITER_DIRECTORY_UNAVAILABLE") from None
        meta=path.stat()
        if not stat.S_ISDIR(meta.st_mode) or meta.st_mode&0o077:
            raise WriterOwnershipError("WRITER_DIRECTORY_UNSAFE")
    return base

def _paths(root,broker,account):
    if broker not in BROKERS or not isinstance(account,str) or not ACCOUNT.fullmatch(account) or ".." in account:
        raise WriterOwnershipError("BROKER_ACCOUNT_INVALID")
    folder=_folder(root)
    token=hashlib.sha256((broker+"|"+account).encode()).hexdigest()
    return folder/(broker+"-"+token+".lock"),folder/(broker+"-"+token+".json"),token

def _private_read(path,token,broker):
    if path.is_symlink():raise WriterOwnershipError("WRITER_OWNER_SYMLINK")
    if not path.exists():return {"owner":"V1","generation":None}
    flags=os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_CLOEXEC",0)
    try:
        fd=os.open(path,flags)
        try:
            meta=os.fstat(fd)
            if not stat.S_ISREG(meta.st_mode) or meta.st_mode&0o077 or meta.st_size>4000:
                raise WriterOwnershipError("WRITER_OWNER_FILE_UNSAFE")
            with os.fdopen(fd,"r",encoding="utf8") as f:
                fd=None
                data=json.load(f)
        finally:
            if fd is not None:os.close(fd)
    except (OSError,ValueError,TypeError,UnicodeError,json.JSONDecodeError):
        raise WriterOwnershipError("WRITER_OWNER_FILE_UNVERIFIED") from None
    if (not isinstance(data,dict) or data.get("schema")!=1 or
            data.get("broker")!=broker or data.get("account_digest")!=token or
            data.get("owner") not in ("V1","V2") or
            not isinstance(data.get("generation"),str) or
            not GENERATION.fullmatch(data["generation"])):
        raise WriterOwnershipError("WRITER_OWNER_FILE_INVALID")
    return data

@contextmanager
def account_writer_scope(root,broker,account,*,owner="V1",generation=None):
    """Keep exclusive file lock held THROUGH intent persist, POST and acknowledgment.

    Does not read credentials or brokerage prices. A V2 file without exact
    owner/generation does not authorize V1 or V2 to submit.
    """
    if owner not in ("V1","V2"):
        raise WriterOwnershipError("WRITER_OWNER_INVALID")
    lock,record,digest=_paths(root,broker,account)
    flags=os.O_CREAT|os.O_RDWR|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_CLOEXEC",0)
    try:
        fd=os.open(lock,flags,0o600)
    except OSError:
        raise WriterOwnershipError("WRITER_LOCK_UNAVAILABLE") from None
    try:
        st=os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_mode&0o077:
            raise WriterOwnershipError("WRITER_LOCK_UNSAFE")
        fcntl.flock(fd,fcntl.LOCK_EX)
        state=_private_read(record,digest,broker)
        if state["owner"]!=owner:
            raise WriterOwnershipError("ACCOUNT_OWNED_BY_OTHER_WRITER")
        if owner=="V2" and (not isinstance(generation,str) or
                            state["generation"]!=generation):
            raise WriterOwnershipError("V2_WRITER_GENERATION_MISMATCH")
        yield state
    finally:
        fcntl.flock(fd,fcntl.LOCK_UN)
        os.close(fd)

def inspect_ownership(root,broker,account):
    """Returns redacted local ownership state; never an execution permission."""
    lock,record,digest=_paths(root,broker,account)
    return _private_read(record,digest,broker)
