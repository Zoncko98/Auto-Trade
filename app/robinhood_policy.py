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
def save_policy(root,payload,accounts,pairs):
    if not isinstance(payload,dict):raise PolicyError("Malformed policy")
    account=payload.get("account")
    available=[a for a in accounts if isinstance(a,dict) and a.get("account_number")==account
               and a.get("status")=="active" and a.get("is_api_tradable") is True
               and a.get("buying_power_currency")=="USD"]
    if len(available)!=1:raise PolicyError("Select one verified API-tradable USD account")
    maximum=_amount(payload.get("max_order_usd"),Decimal("1"),Decimal("25"))
    enabled=payload.get("enabled")
    if type(enabled) is not bool:raise PolicyError("Explicit trading permission required")
    if not isinstance(pairs,list):raise PolicyError("Broker trading pairs unavailable")
    from robinhood_crypto_gateway import PAIR
    minimums=[]
    for row in pairs:
        if (isinstance(row,dict) and isinstance(row.get("symbol"),str) and PAIR.fullmatch(row["symbol"])
            and row.get("is_api_tradable") is True):
            try:
                v=_amount(row.get("min_order_amount"),Decimal("0.00000001"),Decimal("25"))
                inc=_amount(row.get("asset_increment"),Decimal("0.00000001"),Decimal("100"))
                maximum_asset=_amount(row.get("max_order_size"),Decimal("0.00000001"),Decimal("1000000000"))
                minimums.append(v)
            except PolicyError:continue
    if enabled and not minimums:raise PolicyError("No verified broker-tradable crypto pair")
    broker_min=min(minimums) if minimums else Decimal("0")
    cash=_amount(available[0].get("buying_power"),Decimal("0"),Decimal("1000000000"))
    if enabled and min(maximum,cash*Decimal("0.25"))<broker_min:
        raise PolicyError("Buying power below verified Robinhood minimum at 25% cash allocation")
    doc={"account":account,"enabled":enabled,"max_order_usd":str(maximum),
         "verified_broker_minimum_usd":str(broker_min)}
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
