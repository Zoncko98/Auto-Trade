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

def _client(state):
    cfg=_load(state)
    try:
        from webull.core.client import ApiClient
        from webull.trade.trade_client import TradeClient
    except ImportError:
        raise WebullError("Webull official SDK is not installed") from None
    api=ApiClient(cfg["app_key"],cfg["app_secret"],"us")
    api.add_endpoint("us",("api.sandbox.webull.com" if cfg["environment"]=="sandbox" else "api.webull.com"))
    token_dir=Path(state)/"webull"/cfg["environment"]/"tokens"
    token_dir.mkdir(parents=True,mode=0o700,exist_ok=True)
    if token_dir.stat().st_mode & 0o077: raise WebullError("Unsafe token directory permissions")
    api.set_token_dir(str(token_dir))
    _configure_sdk_logging(api)
    return TradeClient(api),cfg["environment"]

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

def status(state):
    if not saved(state):
        return {"provider":"webull","credentials_saved":False,"connected":False,
                "execution_enabled":False,"reason":"Add approved Webull OpenAPI app credentials"}
    try:
        client,env=_client(state)
        accounts=_accounts(_data(client.account_v2.get_account_list()))
        safe=[{"account_id":str(a.get("account_id","")), "account_type":str(a.get("account_type",""))}
              for a in accounts if isinstance(a,dict)]
        return {"provider":"webull","credentials_saved":True,"connected":True,
                "environment":env,"accounts":safe,"execution_enabled":False,
                "reason":"Account access verified. Autonomous Webull order execution is disabled pending end-to-end validation."}
    except (WebullError,ValueError,TypeError,KeyError,OSError) as e:
        return {"provider":"webull","credentials_saved":True,"connected":False,
                "execution_enabled":False,"reason":str(e)[:180]}
    except Exception:
        return {"provider":"webull","credentials_saved":True,"connected":False,
                "execution_enabled":False,"reason":"Webull authentication or account lookup failed"}

def portfolio(state,account_id):
    client,env=_client(state)
    accounts=_accounts(_data(client.account_v2.get_account_list()))
    if not isinstance(account_id,str) or not any(a.get("account_id")==account_id for a in accounts if isinstance(a,dict)):
        raise WebullError("Account not authorized")
    return {"account_id":account_id,"environment":env,
            "balances":_data(client.account_v2.get_account_balance(account_id)),
            "positions":_data(client.account_v2.get_account_position(account_id)),
            "execution_enabled":False}
