"""Operator-controlled Webull stock/crypto execution policy.

Separates account selection from broker credential storage and from the Robinhood
worker. A saved risk plan cannot activate this policy.
"""
import json,os,secrets,stat
from pathlib import Path

class WebullPolicyError(ValueError):pass

# Enabling live Webull orders requires separate broker-sandbox validation.
# Simulated client tests are necessary but cannot establish that Webull will
# accept, fill and correctly reconcile a real order. This stays fail-closed.
LIVE_EXECUTION_VERIFIED=False

DEFAULT={"enabled":False,"stock_account":"","crypto_account":"",
         "trade_stocks":False,"trade_crypto":False}

def _path(state):return Path(state)/"webull"/"trading_policy.json"

def read(state):
    path=_path(state)
    if not path.exists():return dict(DEFAULT)
    st=path.stat()
    if not stat.S_ISREG(st.st_mode) or st.st_mode & 0o077 or st.st_size>4096:
        raise WebullPolicyError("Unsafe trading policy storage")
    obj=json.loads(path.read_text())
    if not isinstance(obj,dict) or set(obj)!=set(DEFAULT):
        raise WebullPolicyError("Trading policy unavailable")
    return validate(obj)

def validate(obj):
    if not isinstance(obj,dict) or set(obj)!=set(DEFAULT):raise WebullPolicyError("Invalid trading policy")
    if any(type(obj[k]) is not bool for k in ("enabled","trade_stocks","trade_crypto")):
        raise WebullPolicyError("Invalid execution flags")
    for field in ("stock_account","crypto_account"):
        val=obj[field]
        if not isinstance(val,str) or len(val)>80 or any(ord(c)<32 for c in val):
            raise WebullPolicyError("Invalid account")
    if obj["enabled"] and not ((obj["trade_stocks"] and obj["stock_account"]) or
                                (obj["trade_crypto"] and obj["crypto_account"])):
        raise WebullPolicyError("Select a broker account and asset class before enabling")
    return dict(obj)

def save(state,payload,accounts,confirmation=None):
    obj=validate(payload)
    current=read(state)
    ids={a.get("account_id") for a in accounts if isinstance(a,dict)}
    for key,asset_flag in (("stock_account","trade_stocks"),("crypto_account","trade_crypto")):
        if obj["enabled"] and obj[asset_flag] and obj[key] not in ids:
            raise WebullPolicyError("Selected Webull account was not authenticated")
    if obj["enabled"] and not LIVE_EXECUTION_VERIFIED:
        raise WebullPolicyError("Webull live execution remains locked until broker sandbox order lifecycle is verified")
    if obj["enabled"] and not current["enabled"] and confirmation!="ENABLE_WEBULL_LIVE":
        raise WebullPolicyError("Explicit live order authorization required")
    if obj["enabled"]:
        from webull_risk import read as risk_read
        risk=risk_read(state)
        if (risk["max_order_usd"]>1000 or risk["max_position_pct"]>10 or
            risk["max_daily_loss_usd"]>250 or risk["max_open_positions"]>10):
            raise WebullPolicyError("Tighten Webull risk limits before enabling live orders")
        # Insist on both market segment flags with explicitly selected accounts.
        if not (obj["trade_stocks"] or obj["trade_crypto"]):
            raise WebullPolicyError("No assets enabled")
    path=_path(state);path.parent.mkdir(parents=True,mode=0o700,exist_ok=True)
    if path.parent.is_symlink() or not path.parent.is_dir():
        raise WebullPolicyError("Unsafe trading policy directory")
    if path.parent.stat().st_mode & 0o077:os.chmod(path.parent,0o700)
    if path.parent.stat().st_mode & 0o077:
        raise WebullPolicyError("Unsafe trading policy directory")
    temp=path.parent/(".trading-"+secrets.token_hex(8))
    fd=os.open(str(temp),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(fd,"w") as out:
            json.dump(obj,out)
            out.flush();os.fsync(out.fileno())
        os.replace(temp,path)
    finally:
        if temp.exists():temp.unlink()
    return obj


def disarm(state):
    """Revoke Webull order permission without contacting the broker."""
    obj=read(state)
    obj["enabled"]=False
    # Write disarmed state even if account access has expired.
    return save(state,obj,[],confirmation=None)
