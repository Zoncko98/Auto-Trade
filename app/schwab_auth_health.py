"""Persistent Schwab OAuth-health gate; no credential contents or network calls.

The live worker records a rejected refresh token once. Supervisor refuses to
restart against the SAME token fingerprint. Reauthorization changes the token,
but journal reconciliation is still mandatory before any order execution.
"""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import stat
import tempfile

NAME="auth_health.json"

def is_revoked_refresh_error(error: BaseException) -> bool:
    # The observed authlib exception is OAuthError with unsupported_token_type
    # and a nested invalid_grant body. Class + diagnostic pair avoids labelling
    # transient HTTP failures or arbitrary exception strings as revoked grants.
    if type(error).__name__ != "OAuthError":
        return False
    message=str(error).lower()
    return ("invalid_grant" in message or
            "refresh token is invalid, expired or revoked" in message)

def _fingerprint(token_path):
    try:
        p=Path(token_path)
        st=p.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_mode & 0o077 or st.st_size < 1:
            return None
        return {"mtime_ns":st.st_mtime_ns, "size":st.st_size, "inode":st.st_ino}
    except (OSError,TypeError,ValueError):
        return None

def mark_reauth_required(live_dir, token_path):
    fingerprint=_fingerprint(token_path)
    if fingerprint is None:
        return False
    target=Path(live_dir)
    target.mkdir(mode=0o700,parents=True,exist_ok=True)
    if target.stat().st_mode & 0o077:
        return False
    payload={"version":1,"state":"REAUTH_REQUIRED",
             "reason":"SCHWAB_REFRESH_TOKEN_REJECTED",
             "token":fingerprint,"at":datetime.now(timezone.utc).isoformat()}
    fd,tmp=tempfile.mkstemp(prefix=".auth-",dir=target)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as handle:
            os.fchmod(handle.fileno(),0o600)
            json.dump(payload,handle,separators=(",",":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp,target/NAME)
        return True
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def reauth_required(state_dir, token_path=None):
    base=Path(state_dir)
    path=base/"live"/NAME
    token=Path(token_path) if token_path is not None else base/"schwab_token.json"
    try:
        st=path.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_mode & 0o077 or st.st_size > 2048:
            return False
        obj=json.loads(path.read_text(encoding="utf-8"))
        return (isinstance(obj,dict) and obj.get("version")==1 and
                obj.get("state")=="REAUTH_REQUIRED" and
                obj.get("token")==_fingerprint(token))
    except (OSError,ValueError,TypeError):
        return False

def clear_verified_reauth(live_dir):
    """Only call after Schwab's signed account lookup actually succeeds."""
    path=Path(live_dir)/NAME
    try:
        st=path.lstat()
        if stat.S_ISREG(st.st_mode) and not (st.st_mode & 0o077):
            path.unlink()
    except OSError:
        pass
