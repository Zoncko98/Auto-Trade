"""Single-user dashboard password rotation, independent of container recreation.

The first login accepts the initial environment password. On rotation, only a
salted PBKDF2 verifier is stored in persistent state and the env fallback is
permanently disabled. Sessions include a revision to revoke every old cookie.
"""
from __future__ import annotations
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import tempfile

MIN_PASSWORD_LENGTH=20
MAX_PASSWORD_LENGTH=256
PBKDF2_ITERATIONS=600_000
FILENAME="profile_auth.json"

class ProfileError(ValueError):
    pass

def _read(state_dir):
    path=Path(state_dir)/FILENAME
    if not path.exists():return None
    stat=path.stat()
    if stat.st_mode & 0o077 or not (0 < stat.st_size <= 4096):
        raise ProfileError("Invalid protected password state")
    try:
        obj=json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(obj,dict) or obj.get("schema")!=1 or
            not isinstance(obj.get("revision"),int) or obj["revision"]<1 or
            not 100_000<=obj.get("iterations",0)<=1_500_000 or
            not isinstance(obj.get("salt"),str) or not isinstance(obj.get("digest"),str)):
            raise ValueError("Invalid authentication state")
        if len(bytes.fromhex(obj["salt"]))!=16 or len(bytes.fromhex(obj["digest"]))!=32:
            raise ValueError("Bad hash dimensions")
        return obj
    except (ValueError,TypeError,KeyError,UnicodeError) as exc:
        raise ProfileError("Invalid protected password state") from exc

def revision(state_dir):
    item=_read(state_dir)
    return item["revision"] if item else 0

def verify(state_dir,password,bootstrap_password):
    if not isinstance(password,str):return False
    item=_read(state_dir)
    if item is None:
        return hmac.compare_digest(password.encode("utf-8"),bootstrap_password.encode("utf-8"))
    actual=hashlib.pbkdf2_hmac("sha256",password.encode("utf-8"),
        bytes.fromhex(item["salt"]),item["iterations"])
    return hmac.compare_digest(actual,bytes.fromhex(item["digest"]))

def rotate(state_dir,current,new,bootstrap_password):
    if not isinstance(current,str) or not isinstance(new,str):
        raise ProfileError("Current and new password are required")
    if (not MIN_PASSWORD_LENGTH <= len(new) <= MAX_PASSWORD_LENGTH or
        any(ord(ch)<32 or ord(ch)==127 for ch in new) or not new.strip()):
        raise ProfileError("Use a new password of 20–256 characters without control characters")
    root=Path(state_dir)
    root.mkdir(parents=True,exist_ok=True)
    lock=root/"profile_auth.lock"
    fd=os.open(lock,os.O_CREAT|os.O_RDWR,0o600)
    try:
        os.fchmod(fd,0o600)
        fcntl.flock(fd,fcntl.LOCK_EX)
        if not verify(root,current,bootstrap_password):
            raise ProfileError("Current password is incorrect")
        if hmac.compare_digest(current.encode("utf-8"),new.encode("utf-8")):
            raise ProfileError("New password must differ from current password")
        rev=revision(root)+1
        salt=secrets.token_bytes(16)
        digest=hashlib.pbkdf2_hmac("sha256",new.encode("utf-8"),salt,PBKDF2_ITERATIONS)
        record={"schema":1,"revision":rev,"iterations":PBKDF2_ITERATIONS,
                "salt":salt.hex(),"digest":digest.hex()}
        tmp_fd,tmp=tempfile.mkstemp(prefix=".profile-",dir=root)
        try:
            with os.fdopen(tmp_fd,"w",encoding="utf-8") as handle:
                os.fchmod(handle.fileno(),0o600)
                json.dump(record,handle,sort_keys=True)
                handle.flush();os.fsync(handle.fileno())
            os.replace(tmp,root/FILENAME)
            os.chmod(root/FILENAME,0o600)
        finally:
            if os.path.exists(tmp):os.unlink(tmp)
        return rev
    finally:
        fcntl.flock(fd,fcntl.LOCK_UN)
        os.close(fd)
