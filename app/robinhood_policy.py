"""Protected per-account Robinhood risk settings. Saving never arms trading."""
import json,os,tempfile
from decimal import Decimal,InvalidOperation
from pathlib import Path

class PolicyError(ValueError):pass

DEFAULTS={
 "max_order_usd":"5",
 "max_total_exposure_usd":"25",
 "max_daily_loss_usd":"5",
 "max_open_positions":3,
 "min_hold_minutes":15,
 "min_profit_pct":"1.0",
 "stop_loss_pct":"2.0",
 "fee_buffer_pct":"0.25",
 "reentry_cooldown_minutes":30,
}

def _amount(x,low,high):
    try:v=Decimal(str(x))
    except (InvalidOperation,TypeError,ValueError):raise PolicyError("Invalid monetary limit") from None
    if not v.is_finite() or not low<=v<=high:raise PolicyError("Risk limit out of permitted range")
    return v

def _integer(x,low,high,name):
    if isinstance(x,bool):raise PolicyError(name+" must be an integer")
    try:value=int(x)
    except (ValueError,TypeError):raise PolicyError(name+" must be an integer") from None
    if not low<=value<=high:raise PolicyError(name+" outside permitted range")
    return value

def _policy_view(doc,configured=True):
    return {"configured":configured,"enabled":doc.get("enabled") is True,
            "max_order_usd":str(doc.get("max_order_usd",DEFAULTS["max_order_usd"])),
            "max_total_exposure_usd":str(doc.get("max_total_exposure_usd",DEFAULTS["max_total_exposure_usd"])),
            "max_daily_loss_usd":str(doc.get("max_daily_loss_usd",DEFAULTS["max_daily_loss_usd"])),
            "max_open_positions":int(doc.get("max_open_positions",DEFAULTS["max_open_positions"])),
            "min_hold_minutes":int(doc.get("min_hold_minutes",DEFAULTS["min_hold_minutes"])),
            "min_profit_pct":str(doc.get("min_profit_pct",DEFAULTS["min_profit_pct"])),
            "stop_loss_pct":str(doc.get("stop_loss_pct",DEFAULTS["stop_loss_pct"])),
            "fee_buffer_pct":str(doc.get("fee_buffer_pct",DEFAULTS["fee_buffer_pct"])),
            "reentry_cooldown_minutes":int(doc.get("reentry_cooldown_minutes",DEFAULTS["reentry_cooldown_minutes"])),
            "verified_broker_minimum_usd":str(doc.get("verified_broker_minimum_usd","0")),
            "account":doc.get("account")}

def read_policy(root):
    path=Path(root)/"robinhood"/"risk_policy.json"
    try:
        doc=json.loads(path.read_text())
        if not isinstance(doc,dict):raise ValueError
    except FileNotFoundError:
        return _policy_view(dict(DEFAULTS,enabled=False,verified_broker_minimum_usd="0",account=None),False)
    except (ValueError,TypeError,OSError):
        raise PolicyError("Risk policy unreadable")
    return _policy_view(doc)

def save_policy(root,payload,accounts,pairs):
    if not isinstance(payload,dict):raise PolicyError("Malformed policy")
    current=read_policy(root)
    account=payload.get("account")
    available=[a for a in accounts if isinstance(a,dict) and a.get("account_number")==account
               and a.get("status")=="active" and a.get("is_api_tradable") is True
               and a.get("buying_power_currency")=="USD"]
    if len(available)!=1:raise PolicyError("Select one verified API-tradable USD account")
    maximum=_amount(payload.get("max_order_usd",current["max_order_usd"]),Decimal("1"),Decimal("25"))
    total_exposure=_amount(payload.get("max_total_exposure_usd",current["max_total_exposure_usd"]),
                           maximum,Decimal("250"))
    daily_loss=_amount(payload.get("max_daily_loss_usd",current["max_daily_loss_usd"]),
                       Decimal("0.10"),Decimal("100"))
    open_positions=_integer(payload.get("max_open_positions",current["max_open_positions"]),1,10,"Open-position limit")
    min_hold=_integer(payload.get("min_hold_minutes",current["min_hold_minutes"]),1,1440,"Minimum hold")
    min_profit=_amount(payload.get("min_profit_pct",current["min_profit_pct"]),Decimal("0.10"),Decimal("10"))
    stop_loss=_amount(payload.get("stop_loss_pct",current["stop_loss_pct"]),Decimal("0.50"),Decimal("15"))
    fee_buffer=_amount(payload.get("fee_buffer_pct",current["fee_buffer_pct"]),Decimal("0"),Decimal("2"))
    cooldown=_integer(payload.get("reentry_cooldown_minutes",current["reentry_cooldown_minutes"]),0,1440,"Re-entry cooldown")
    enabled=payload.get("enabled")
    if type(enabled) is not bool:raise PolicyError("Explicit trading permission required")
    if not isinstance(pairs,list):raise PolicyError("Broker trading pairs unavailable")
    from robinhood_crypto_gateway import PAIR
    minimums=[]
    for row in pairs:
        if (isinstance(row,dict) and isinstance(row.get("symbol"),str) and PAIR.fullmatch(row["symbol"])
            and row.get("is_api_tradable") is True):
            try:
                minimums.append(_amount(row.get("min_order_amount"),Decimal("0.00000001"),Decimal("25")))
                _amount(row.get("asset_increment"),Decimal("0.00000001"),Decimal("100"))
                _amount(row.get("max_order_size"),Decimal("0.00000001"),Decimal("1000000000"))
            except PolicyError:continue
    if enabled and not minimums:raise PolicyError("No verified broker-tradable crypto pair")
    broker_min=min(minimums) if minimums else Decimal("0")
    cash=_amount(available[0].get("buying_power"),Decimal("0"),Decimal("1000000000"))
    if enabled and min(maximum,cash*Decimal("0.25"))<broker_min:
        raise PolicyError("Buying power below verified Robinhood minimum at 25% cash allocation")
    doc={"account":account,"enabled":enabled,"max_order_usd":str(maximum),
         "max_total_exposure_usd":str(total_exposure),"max_daily_loss_usd":str(daily_loss),
         "max_open_positions":open_positions,"min_hold_minutes":min_hold,
         "min_profit_pct":str(min_profit),"stop_loss_pct":str(stop_loss),
         "fee_buffer_pct":str(fee_buffer),"reentry_cooldown_minutes":cooldown,
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
