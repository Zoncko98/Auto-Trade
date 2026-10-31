"""One confirmation-bound live-trading toggle; broker identity is checked every enable."""
from pathlib import Path
from unified_config import settings,atomic_save,public_summary,SetupError
from live_dashboard import set_operator_mode
from dashboard_control import write_atomic
from schwab_web_oauth import accounts

def toggle(state,request,account_lookup=accounts):
    if not isinstance(request,dict) or set(request)!={"enable","confirmed","account_hash"}:
        raise SetupError("Invalid live-trading confirmation request")
    if type(request["enable"]) is not bool or type(request["confirmed"]) is not bool:
        raise SetupError("Invalid trading selection")
    new=settings(state)
    if request["enable"]:
        if request["confirmed"] is not True:
            raise SetupError("Confirm that this permits real Schwab orders")
        choice=request["account_hash"]
        if not isinstance(choice,str) or not choice:
            raise SetupError("Select your linked Schwab account")
        # Validate actual Schwab authorization and account ownership at activation.
        registered=account_lookup(state).get("accounts",[])
        if not any(item.get("hash")==choice for item in registered):
            raise SetupError("Selected account is not available through your linked Schwab login")
        new["live_enabled"]=True
        new["live_confirmed"]=True
        new["live_account_hash"]=choice
        # Fail closed until both settings and operator permission are persisted.
        set_operator_mode(state,"paused",write_atomic)
        atomic_save(Path(state)/"config"/"integrations.json",new)
        set_operator_mode(state,"running",write_atomic)
    else:
        # Stop new order intent immediately before worker shutdown.
        set_operator_mode(state,"paused",write_atomic)
        new["live_enabled"]=False
        new["live_confirmed"]=False
        atomic_save(Path(state)/"config"/"integrations.json",new)
    return public_summary(state)
