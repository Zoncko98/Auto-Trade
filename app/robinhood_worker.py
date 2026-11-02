"""Account-scoped Robinhood monitoring and fail-closed execution readiness.

No order writes occur until a separately authorized live execution mode exists.
"""
import json,os,time
from datetime import datetime,timezone
from decimal import Decimal,InvalidOperation
from pathlib import Path
from robinhood_crypto_gateway import RobinhoodCryptoAdapter,RobinhoodUnavailable
from dashboard_control import write_atomic

PAIRS=("BTC-USD","ETH-USD","SOL-USD","DOGE-USD")
def snapshot(client):
    accounts=client.list_accounts()
    out=[]
    for a in accounts:
        if not isinstance(a,dict):continue
        try:
            buying=Decimal(str(a.get("buying_power","0")))
            if not buying.is_finite() or buying<0:raise ValueError
        except (InvalidOperation,ValueError,TypeError):
            buying=None
        out.append({"account_status":str(a.get("status","unknown"))[:32],
           "api_tradable":a.get("is_api_tradable") is True,
           "currency":str(a.get("buying_power_currency",""))[:8],
           "buying_power_usd":str(buying) if buying is not None and a.get("buying_power_currency")=="USD" else None})
    quotes_checked=0
    for pair in PAIRS:
        try:
            q=client.quote(pair)
            if isinstance(q,dict):quotes_checked+=1
        except (RobinhoodUnavailable,ValueError,TypeError,KeyError):
            continue
    return {"accounts":out,"quotes_checked":quotes_checked,"pairs_checked":len(PAIRS)}

def run_once(state,client):
    result=snapshot(client)
    from robinhood_order_journal import OrderJournal
    journal=OrderJournal(state)
    pending=journal.pending()
    account_rows=client.list_accounts()
    if pending:
        matched=[a for a in account_rows if isinstance(a,dict) and
                 a.get("account_number")==pending[0].get("account")]
        if matched:
            journal.reconcile(pending[0]["account"],client.orders(pending[0]["account"]))
    pending=journal.pending()
    from robinhood_risk import preflight,RiskDenied
    risk_check="NOT_CONFIGURED"
    # Never infer live authorization from the existence of API credentials.
    policy_path=Path(state)/"robinhood"/"risk_policy.json"
    try:
        policy=json.loads(policy_path.read_text())
        rows=client.list_accounts()
        selected=next((a for a in rows if isinstance(a,dict)
                       and a.get("account_number")==policy.get("account")),None)
        if selected is None:raise RiskDenied("Configured account not available")
        # Signal and quote qualification is not yet implemented: this is a
        # readiness diagnostic, not authorization to submit an order.
        preflight(selected,policy,"BTC-USD","1","0",len(pending))
        risk_check="ACCOUNT_PREFLIGHT_PASSED_SIGNAL_NOT_CHECKED"
    except FileNotFoundError:
        pass
    except (RiskDenied,ValueError,TypeError,KeyError,StopIteration) as exc:
        risk_check="BLOCKED_"+type(exc).__name__
    result.update({"risk_check":risk_check,"pending_order_intents":len(pending),
       "updated_at":datetime.now(timezone.utc).isoformat(),
       "worker":"monitoring","last_signal":"NOT_VERIFIED",
       "execution_status":"NOT_ARMED",
       "live_orders_allowed":False,"last_order_confirmed":False,
       "reason":"Robinhood strategy, approvals, and reconciliation are not enabled for live execution"})
    write_atomic(Path(state)/"robinhood"/"worker_status.json",result)
    return result

def main():
    state=Path(os.getenv("STATE_DIR","/state"))
    while True:
        try:
            client=RobinhoodCryptoAdapter.from_state(state)
            report=run_once(state,client)
            print("Robinhood monitoring:",report["quotes_checked"],"quote responses",flush=True)
        except (OSError,ValueError,KeyError,TypeError,RobinhoodUnavailable) as exc:
            write_atomic(state/"robinhood"/"worker_status.json",{
                "updated_at":datetime.now(timezone.utc).isoformat(),"worker":"blocked",
                "execution_status":"NOT_ARMED","live_orders_allowed":False,
                "last_order_confirmed":False,"reason":"Broker monitoring unavailable: "+type(exc).__name__})
        time.sleep(180)

if __name__=="__main__":main()
