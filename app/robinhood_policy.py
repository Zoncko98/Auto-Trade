"""Protected per-account Robinhood live-risk settings. Saving never arms trading."""
import json,os,tempfile
from decimal import Decimal,InvalidOperation
from pathlib import Path

class PolicyError(ValueError):pass
def _amount(x,low,high):
    try:v=Decimal(str(x))
    except (InvalidOperation,TypeError,ValueError):raise PolicyError("Invalid monetary limit") from None
    if not v.is_finite() or not low<=v<=high:raise PolicyError("Risk limit out of permitted range")
    return v
def read_policy(root):
    path=Path(root)/"robinhood"/"risk_policy.json"
    try:
        doc=json.loads(path.read_text())
        if not isinstance(doc,dict):raise ValueError
    except FileNotFoundError:
        return {"configured":False,"enabled":False,"max_order_usd":"5","verified_broker_minimum_usd":"0","account":None}
    except (ValueError,TypeError,OSError):
        raise PolicyError("Risk policy unreadable")
    return {"configured":True,"enabled":doc.get("enabled") is True,
            "max_order_usd":str(doc.get("max_order_usd","5")),
            "verified_broker_minimum_usd":str(doc.get("verified_broker_minimum_usd","0")),
            "account":doc.get("account")}
def save_policy(root,payload,accounts):
    if not isinstance(payload,dict):raise PolicyError("Malformed policy")
    account=payload.get("account")
    available=[a for a in accounts if isinstance(a,dict) and a.get("account_number")==account
               and a.get("status")=="active" and a.get("is_api_tradable") is True]
    if len(available)!=1:raise PolicyError("Select one verified API-tradable account")
    maximum=_amount(payload.get("max_order_usd"),Decimal("1"),Decimal("25"))
    minimum=_amount(payload.get("verified_broker_minimum_usd"),Decimal("0"),Decimal("25"))
    # The operator cannot simply assert a verified broker minimum through UI.
    # It remains zero until verified by the broker-metadata workflow.
    if minimum!=0:raise PolicyError("Broker minimum must be independently verified")
    if payload.get("enabled") not in (False,None):raise PolicyError("Live authorization is a separate verified step")
    doc={"account":account,"enabled":False,"max_order_usd":str(maximum),
         "verified_broker_minimum_usd":"0"}
    path=Path(root)/"robinhood"/"risk_policy.json"
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(dir=path.parent,prefix=".risk-")
    try:
        with os.fdopen(fd,"w") as f:
            os.fchmod(f.fileno(),0o600);json.dump(doc,f);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
    return read_policy(root)
