"""Webull official OpenAPI connection and read-only account adapter.

Uses Webull's published Python SDK. Trading deliberately fails closed until the
account-specific execution and reconciliation worker is integrated and verified.
"""
import json
import os
import logging
import sys
import threading
import stat
import secrets
from pathlib import Path

class WebullError(RuntimeError):
    pass

# Webull TradeClient otherwise initializes an implicit relative file handler for
# webull_trade_sdk.log. The production /app filesystem is intentionally read-only.
# Do not expose SDK signed request headers or account data in process logs.
# SDK logging is disabled; application status returns sanitized error categories.
_SDK_LOG_LOCK = threading.Lock()
_sdk_stream_handler = None

def _configure_sdk_logging(api):
    global _sdk_stream_handler
    with _SDK_LOG_LOCK:
        logger = logging.getLogger("webull.core")
        if _sdk_stream_handler is not None:
            logger.removeHandler(_sdk_stream_handler)
            _sdk_stream_handler.close()
            _sdk_stream_handler = None
        existing = list(logger.handlers)
        # Public SDK API; marks the client as configured, preventing the default
        # TimedRotatingFileHandler inside TradeClient._init_logger.
        api.set_stream_logger(log_level=logging.CRITICAL+1, stream=sys.stderr)
        added = [handler for handler in logger.handlers if handler not in existing]
        if added:
            _sdk_stream_handler = added[-1]

def _file(state):
    return Path(state)/"config"/"webull_openapi.json"

def saved(state):
    return _file(state).is_file()

def store_credentials(state, payload):
    if not isinstance(payload,dict) or set(payload)!={"app_key","app_secret","environment"}:
        raise ValueError("App key, app secret and environment required")
    key=payload["app_key"]; secret=payload["app_secret"]
    env=payload["environment"]
    if not isinstance(key,str) or not (8<=len(key)<=256) or any(c.isspace() for c in key):
        raise ValueError("Invalid app key")
    if not isinstance(secret,str) or not (8<=len(secret)<=512) or any(c.isspace() for c in secret):
        raise ValueError("Invalid app secret")
    if env not in ("sandbox","production"):
        raise ValueError("Invalid environment")
    # Rotating broker credentials must revoke any previous live authorization
    # before changing the signing principal. Never carry an armed policy over.
    from webull_trade_config import disarm
    disarm(state)
    folder=_file(state).parent
    folder.mkdir(mode=0o700,parents=True,exist_ok=True)
    if folder.stat().st_mode & 0o077:
        raise WebullError("Unsafe credentials directory permissions")
    tmp=folder/(".webull-"+secrets.token_hex(10))
    fd=os.open(str(tmp),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(fd,"w") as out:
            json.dump({"app_key":key,"app_secret":secret,"environment":env},out)
            out.flush();os.fsync(out.fileno())
        os.replace(tmp,_file(state))
    finally:
        if tmp.exists():tmp.unlink()
    return {"saved":True,"authenticated":False,"environment":env,
            "message":"Webull credentials saved. Check connection to verify authorized accounts. Live trading stays disabled."}

def _load(state):
    f=_file(state)
    s=f.stat()
    if not stat.S_ISREG(s.st_mode) or s.st_mode & 0o077 or s.st_size>4096:
        raise WebullError("Unsafe Webull credential file")
    cfg=json.loads(f.read_text())
    if cfg.get("environment") not in ("sandbox","production"):
        raise WebullError("Invalid Webull environment")
    return cfg

def _api(state):
    cfg=_load(state)
    try:
        from webull.core.client import ApiClient
    except ImportError:
        raise WebullError("Webull official SDK is not installed") from None
    api=ApiClient(cfg["app_key"],cfg["app_secret"],"us")
    api.add_endpoint("us",("api.sandbox.webull.com" if cfg["environment"]=="sandbox" else "api.webull.com"))
    token_dir=Path(state)/"webull"/cfg["environment"]/"tokens"
    token_dir.mkdir(parents=True,mode=0o700,exist_ok=True)
    if token_dir.stat().st_mode & 0o077: raise WebullError("Unsafe token directory permissions")
    api.set_token_dir(str(token_dir))
    _configure_sdk_logging(api)
    return api,cfg["environment"]

def _client(state):
    try:
        from webull.trade.trade_client import TradeClient
    except ImportError:raise WebullError("Webull official SDK is not installed") from None
    api,env=_api(state)
    return TradeClient(api),env

def _data(response):
    if response.status_code != 200:
        raise WebullError("Webull API rejected request (HTTP "+str(response.status_code)+")")
    data=response.json()
    if not isinstance(data,(dict,list)):
        raise WebullError("Unexpected Webull response")
    return data

def _accounts(data):
    if isinstance(data,list):return data
    for k in ("accounts","data","list"):
        if isinstance(data.get(k),list):return data[k]
        if isinstance(data.get(k),dict):
            for sub in ("accounts","list"):
                if isinstance(data[k].get(sub),list):return data[k][sub]
    raise WebullError("Unexpected Webull account list format")

def _verified_worker_accounts(state, environment):
    """Read-only account verification from a fresh, authenticated worker cycle.

    The worker calls the real Webull account list every 90 seconds. Reusing that
    signed-broker result for the *dashboard only* avoids hammering Webull when
    several widgets refresh simultaneously. Broker writes still run their own
    full live checks; worker snapshots never authorize an order.
    """
    from datetime import datetime,timezone
    root=Path(state)
    file=root/"webull"/"worker_status.json"
    credential=_file(state)
    try:
        st=file.stat()
        if (not stat.S_ISREG(st.st_mode) or st.st_mode & 0o077
                or st.st_size>131072 or st.st_mtime_ns<credential.stat().st_mtime_ns):
            return None
        report=json.loads(file.read_text())
        if (not isinstance(report,dict) or report.get("worker")!="RUNNING"
                or report.get("environment")!=environment):
            return None
        at=datetime.fromisoformat(str(report["updated_at"]).replace("Z","+00:00"))
        if at.tzinfo is None:return None
        age=(datetime.now(timezone.utc)-at.astimezone(timezone.utc)).total_seconds()
        if not 0<=age<=180:return None
        accounts=report.get("broker_accounts")
        if not isinstance(accounts,list) or not 1<=len(accounts)<=20:return None
        safe=[]
        for row in accounts:
            if not isinstance(row,dict):return None
            ident=row.get("account_id")
            kind=row.get("account_type")
            if (not isinstance(ident,str) or not 1<=len(ident)<=80
                    or any(ord(c)<32 for c in ident)
                    or not isinstance(kind,str) or not 1<=len(kind)<=80
                    or any(ord(c)<32 for c in kind)):
                return None
            safe.append({"account_id":ident,"account_type":kind})
        if len({a["account_id"] for a in safe})!=len(safe):return None
        return safe,at.isoformat()
    except (OSError,ValueError,TypeError,KeyError,OverflowError,AttributeError):
        return None


def status(state):
    if not saved(state):
        return {"provider":"webull","credentials_saved":False,"connected":False,
                "execution_enabled":False,"reason":"Add approved Webull OpenAPI app credentials"}
    try:
        # A recent worker's independently verified account list is sufficient
        # for read-only UI status. Stale records and credential rotations force
        # fresh SDK verification instead of claiming an old account is live.
        environment=_load(state)["environment"]
        worker=_verified_worker_accounts(state,environment)
        if worker is not None:
            safe,verified_at=worker
            verification_source="recent_authenticated_worker"
        else:
            from webull_broker import WebullBroker
            broker=WebullBroker(state)
            raw=broker.accounts()
            safe=[{"account_id":a["account_id"],
                   "account_type":str(a.get("account_class") or a.get("account_type") or "")}
                  for a in raw]
            verified_at=None
            verification_source="direct_webull_api"
        from webull_trade_config import read as read_policy
        policy=read_policy(state)
        selected_stock=policy["stock_account"] if policy["trade_stocks"] else ""
        selected_crypto=policy["crypto_account"] if policy["trade_crypto"] else ""
        known={a["account_id"] for a in safe}
        if selected_stock not in known:selected_stock=""
        if selected_crypto not in known:selected_crypto=""
        # A live-policy flag is user authorization, not a broker ACK or fill.
        live=bool(policy["enabled"] and environment=="production")
        return {"provider":"webull","credentials_saved":True,"connected":True,
                "environment":environment,"accounts":safe,
                "account_verification_source":verification_source,
                "account_verified_at":verified_at,
                "selected_stock_account":selected_stock,
                "selected_crypto_account":selected_crypto,
                "operator_live_policy_armed":live,
                "execution_enabled":live,
                "reason":("Recent Webull worker account verification; broker risk and order checks still required"
                          if verification_source=="recent_authenticated_worker"
                          else "Webull API account verification succeeded; broker risk and order checks still required")}
    except (WebullError,ValueError,TypeError,KeyError,OSError) as exc:
        reason=("Webull API rate limit while verifying account (HTTP 429)"
                if "429" in str(exc) else "Webull account lookup or saved policy unavailable")
        return {"provider":"webull","credentials_saved":True,"connected":False,
                "execution_enabled":False,"reason":reason}
    except Exception:
        return {"provider":"webull","credentials_saved":True,"connected":False,
                "execution_enabled":False,
                "reason":"Webull authentication or account lookup failed"}

def portfolio(state,account_id):
    from webull_broker import WebullBroker
    broker=WebullBroker(state)
    broker.verify_account(account_id)
    return {"account_id":account_id,"environment":broker.environment,
            "balances":broker.balance(account_id),
            "positions":broker.positions(account_id),
            "execution_enabled":False}
