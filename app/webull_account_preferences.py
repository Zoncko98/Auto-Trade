"""Explicit Webull margin-class account opt-in; never enables borrowing or live orders."""
import json
import os
import secrets
import stat
from pathlib import Path

DEFAULT={"allow_margin_accounts":False}

class PreferenceError(ValueError):
    pass

def _path(state):
    return Path(state)/"webull"/"account_preferences.json"

def read(state):
    target=_path(state)
    if not target.exists():
        return dict(DEFAULT)
    info=target.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size>1024:
        raise PreferenceError("Unsafe Webull account preference file")
    obj=json.loads(target.read_text())
    if not isinstance(obj,dict) or set(obj)!=set(DEFAULT) or type(obj["allow_margin_accounts"]) is not bool:
        raise PreferenceError("Invalid Webull account preference")
    return dict(obj)

def save(state,payload):
    if not isinstance(payload,dict) or set(payload)!=set(DEFAULT) or type(payload["allow_margin_accounts"]) is not bool:
        raise PreferenceError("Expected explicit margin-account preference")
    target=_path(state)
    folder=target.parent
    folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    if folder.is_symlink() or not folder.is_dir() or folder.stat().st_mode & 0o077:
        raise PreferenceError("Unsafe Webull settings directory")
    tmp=folder/(".account-preferences-"+secrets.token_hex(10))
    fd=os.open(str(tmp),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    try:
        with os.fdopen(fd,"w") as out:
            json.dump(payload,out)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp,target)
    finally:
        if tmp.exists():tmp.unlink()
    return dict(payload)
