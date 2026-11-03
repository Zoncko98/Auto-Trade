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
    # One shared worker records observed crypto momentum and keeps the AI
    # approval boundary closed until a validated crypto research path exists.
    from robinhood_crypto_signals import observe
    from dashboard_control import write_atomic
    history_path=Path(state)/"robinhood"/"quote_history.json"
    try:
        history=json.loads(history_path.read_text())
        if not isinstance(history,list):history=[]
    except (OSError,ValueError,TypeError):
        history=[]
    observations=[]
    for symbol in PAIRS:
        try:
            observations.append(observe(history,symbol,client.quote(symbol)))
        except (RobinhoodUnavailable,ValueError,TypeError,KeyError):
            continue
    history=(history+[{"symbol":r["symbol"],"mid":r["mid"],"at":r["at"]}
                       for r in observations])[-96:]
    write_atomic(history_path,history)
    signal_candidates=[r for r in observations if r["technical_approved"]]
    result["last_signal"]=(signal_candidates[0]["symbol"]+": MOMENTUM_CANDIDATE"
                          if signal_candidates else
                          "NO_SIGNAL" if observations else "QUOTE_UNAVAILABLE")
    result["signal_diagnostics"]=" · ".join(
        r["symbol"]+": "+r["signal"]+
        (" ("+str(r["momentum_pct"])+"% momentum, "+str(r["spread_pct"])+"% spread)" if r.get("momentum_pct") is not None else "")
        for r in observations) or "No valid broker quotes"
    result["observations"]=len(observations)
    result["ai_review_status"]="NOT_INVOKED_NO_TECHNICAL_CANDIDATE"
    result["ai_reason"]="Ollama review requires a qualified technical candidate; no trade decision was requested"
    # Read-only Ollama model catalog proves service/config availability without
    # fabricating a trading decision or spending tokens on every quote.
    from local_ai_gateway import installed_models, _settings, LocalAIUnavailable
    try:
        _, configured_model=_settings()
        models=installed_models()
        result["ai_connection_status"]="READY" if configured_model in models else "MODEL_NOT_INSTALLED"
        result["ai_model"]=configured_model
    except (LocalAIUnavailable,OSError,ValueError,TypeError):
        result["ai_connection_status"]="UNAVAILABLE"
    approved_signal=None
    if signal_candidates:
        # The same configured AI_PROVIDER, LOCAL_AI_URL and LOCAL_AI_MODEL
        # are used by Schwab and paper. Only public timestamped news is sent.
        from ai_research import approve_entry,research_evidence
        target=signal_candidates[0]
        approved,reason=approve_entry(target["symbol"],datetime.now(timezone.utc))
        evidence=research_evidence(target["symbol"],datetime.now(timezone.utc))
        result["ai_review_status"]="PASS" if approved else "VETO_OR_UNAVAILABLE"
        result["ai_model"]=evidence.get("model","unavailable")
        result["ai_reason"]=reason[:500]
        if result.get("ai_connection_status")=="READY":
            result["ai_connection_status"]="REVIEW_PERFORMED"
        result["last_signal"]=target["symbol"]+": "+result["ai_review_status"]
        if approved:
            approved_signal=dict(target,ai_approved=True)
    from robinhood_order_journal import OrderJournal,UnreconciledOrder
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
    # Only a fresh independently approved signal may reach the signed order
    # adapter. Account risk policy must already exist and be enabled.
    execution="NOT_ARMED"
    order_confirmed=False
    if approved_signal is not None:
        try:
            from robinhood_order_pass import submit_approved,OrderPassBlocked
            from robinhood_crypto_execution import RobinhoodCryptoTradingAdapter
            policy=json.loads(policy_path.read_text())
            if policy.get("enabled") is not True:
                raise OrderPassBlocked("Account live trading policy not enabled")
            trader=RobinhoodCryptoTradingAdapter.from_state_authorized(state,policy)
            receipt=submit_approved(state,trader,policy,approved_signal)
            execution="ORDER_ACCEPTED" if receipt["broker_acknowledged"] else "SUBMITTED_UNCONFIRMED"
            # Even accepted orders do not become fills until broker reports
            # executed quantity and the journal reconciles them.
            if receipt["broker_acknowledged"]:
                journal.reconcile(policy["account"],trader.orders(policy["account"]))
                order_confirmed=any(
                    row.get("client_order_id")==receipt["client_order_id"]
                    and row.get("status")=="filled"
                    for row in journal.load()["orders"])
        except (OSError,ValueError,KeyError,TypeError,
                RobinhoodUnavailable,OrderPassBlocked,RiskDenied,
                UnreconciledOrder) as exc:
            execution="BLOCKED_"+type(exc).__name__
    result.update({"risk_check":risk_check,"pending_order_intents":len(journal.pending()),
       "updated_at":datetime.now(timezone.utc).isoformat(),
       "worker":"monitoring",
       "execution_status":execution,
       "live_orders_allowed":execution in ("ORDER_ACCEPTED","SUBMITTED_UNCONFIRMED"),
       "last_order_confirmed":order_confirmed,
       "reason":"Order submission requires explicit account risk approval and broker-confirmed reconciliation"})
    write_atomic(Path(state)/"robinhood"/"worker_status.json",result)
    # Bounded, broker-specific evidence. Never invent a model decision or fill.
    evidence_path=Path(state)/"robinhood"/"decision_history.json"
    try:
        evidence=json.loads(evidence_path.read_text())
        if not isinstance(evidence,list):evidence=[]
    except (OSError,ValueError,TypeError):evidence=[]
    evidence.append({"at":result["updated_at"],"signal":result.get("last_signal"),
        "ai_review_status":result.get("ai_review_status"),"ai_connection_status":result.get("ai_connection_status"),
        "ai_model":result.get("ai_model"),
        "ai_reason":result.get("ai_reason"),"execution_status":result.get("execution_status"),
        "risk_check":result.get("risk_check")})
    write_atomic(evidence_path,evidence[-100:])
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
