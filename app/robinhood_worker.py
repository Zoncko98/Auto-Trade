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

def ai_review_category(approved,reason):
    """Never conflate a missing news source, a model failure and an AI veto."""
    if approved:return "PASS"
    if not isinstance(reason,str):return "AI_UNAVAILABLE"
    if "No headlines explicitly tied" in reason or "No independently timestamped news" in reason:
        return "NEWS_EVIDENCE_MISSING"
    if "Recent news unavailable" in reason or "News feed exceeds size" in reason:
        return "NEWS_FEED_UNAVAILABLE"
    if "AI news gate NO TRADE" in reason:return "AI_NO_TRADE"
    if "AI research unavailable" in reason:return "AI_UNAVAILABLE"
    return "AI_REVIEW_BLOCKED"

def revalidate_buy_signal(state,client,signal,now=None):
    """Re-check price trend and venue after slow AI; never renew a stale signal blindly."""
    from robinhood_crypto_signals import observe
    from robinhood_order_pass import OrderPassBlocked,_quote_prices
    from coinbase_market_feed import read_snapshot
    now=now or datetime.now(timezone.utc)
    symbol=signal.get("symbol")
    if not isinstance(symbol,str):
        raise OrderPassBlocked("AI-approved signal missing symbol")
    try:
        age=(now-datetime.fromisoformat(signal["at"].replace("Z","+00:00"))).total_seconds()
    except (ValueError,KeyError,TypeError,AttributeError):
        raise OrderPassBlocked("AI-approved signal timestamp invalid") from None
    if age<0:raise OrderPassBlocked("AI-approved signal timestamp is in the future")
    if age<=60:return signal
    broker_quote=client.quote(symbol)
    broker_bid,broker_ask=_quote_prices(broker_quote,symbol)
    if (broker_ask-broker_bid)/broker_ask*100>Decimal("0.5"):
        raise OrderPassBlocked("Fresh broker spread exceeds 0.5%")
    original=Decimal(str(signal.get("mid")))
    refreshed=None
    if str(signal.get("source","")).startswith("COINBASE_"):
        feed=read_snapshot(state,now)
        if symbol not in feed["quotes"]:
            raise OrderPassBlocked("Fresh Coinbase candidate quote unavailable after AI review")
        refreshed=observe(feed["history"].get(symbol,[]),symbol,feed["quotes"][symbol],now)
        candidate=Decimal(str(refreshed["mid"]))
        broker_mid=(broker_bid+broker_ask)/2
        if abs(broker_mid/candidate-1)*100>Decimal("0.75"):
            raise OrderPassBlocked("Coinbase and Robinhood prices diverged after AI review")
    else:
        try:
            history=json.loads((Path(state)/"robinhood"/"quote_history.json").read_text())
        except (OSError,ValueError,TypeError):
            raise OrderPassBlocked("Cannot revalidate signal without price history") from None
        if not isinstance(history,list):
            raise OrderPassBlocked("Price history invalid for AI revalidation")
        refreshed=observe(history,symbol,broker_quote,now)
    if refreshed.get("technical_approved") is not True:
        raise OrderPassBlocked("Signal expired during AI review; refreshed technical check: "+
                               str(refreshed.get("signal_reason","not qualified"))[:110])
    refreshed_mid=Decimal(str(refreshed["mid"]))
    if original<=0 or abs(refreshed_mid/original-1)*100>Decimal("0.75"):
        raise OrderPassBlocked("Signal price drift exceeded 0.75% during AI review")
    refreshed.update(ai_approved=True,ai_revalidated=True,
                     revalidated_after_ai_seconds=round(age,2))
    return refreshed

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

def run_once(state,client,feed=None):
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
    # Build the scan universe from real broker trading-pair metadata, never
    # fabricated listings. Keep a bounded batch per cycle to protect the API.
    from robinhood_crypto_gateway import PAIR as PAIR_REGEX
    try:
        metadata=client.trading_pairs()
        universe=sorted({row["symbol"] for row in metadata if isinstance(row,dict)
            and row.get("is_api_tradable") is True and row.get("quote_code")=="USD"
            and isinstance(row.get("symbol"),str) and PAIR_REGEX.fullmatch(row["symbol"])})
    except (RobinhoodUnavailable,ValueError,TypeError,KeyError):
        universe=[]
    if not universe:
        universe=list(PAIRS)
    from coinbase_market_feed import read_snapshot
    market=read_snapshot(state)
    if feed is not None:
        feed.update_symbols(universe)
    result["coinbase_feed"]=market["state"]
    result["coinbase_live_pairs"]=len(market["quotes"])
    cursor_path=Path(state)/"robinhood"/"universe_cursor.json"
    try:
        cursor=int(json.loads(cursor_path.read_text()).get("offset",0))
    except (OSError,ValueError,TypeError,AttributeError):cursor=0
    start=cursor%len(universe)
    rotating=[universe[(start+i)%len(universe)] for i in range(min(24,len(universe)))]
    # Bot-owned positions are risk-managed every cycle, not only when the
    # rotating discovery cursor happens to reach them.
    try:
        from robinhood_order_journal import OrderJournal
        managed=list(OrderJournal(state).positions())
    except (OSError,ValueError,TypeError):
        managed=[]
    batch=list(dict.fromkeys(managed+rotating))
    write_atomic(cursor_path,{"offset":(start+len(rotating))%len(universe)})
    result["universe_size"]=len(universe)
    result["scan_batch"]=batch
    observations=[];broker_observations=[];coinbase_used=0
    from robinhood_order_pass import _quote_prices
    for symbol in batch:
        try:
            if symbol in market["quotes"]:
                points=market["history"].get(symbol,[])
                # Remove the latest same-bucket sample; observe() appends the
                # independently validated current Coinbase bid/ask midpoint.
                recent=[x for x in points if
                        (datetime.now(timezone.utc)-
                         datetime.fromisoformat(x["at"])).total_seconds()>=20]
                row=observe(recent,symbol,market["quotes"][symbol])
                row["source"]="COINBASE_WS" if market.get("state")=="LIVE" else "COINBASE_RECENT_CACHE"
                coinbase_used+=1
                if row.get("technical_approved") or row.get("technical_exit"):
                    rb,ra=_quote_prices(client.quote(symbol),symbol)
                    cb,ca=_quote_prices(market["quotes"][symbol],symbol)
                    cb_mid=(cb+ca)/2;rb_mid=(rb+ra)/2
                    if abs(rb_mid/cb_mid-1)*100>Decimal("0.75") or (ra-rb)/ra*100>Decimal("0.5"):
                        row["technical_approved"]=False
                        row["technical_exit"]=False
                        row["signal"]="VENUE_PRICE_MISMATCH"
                observations.append(row)
            else:
                row=observe(history,symbol,client.quote(symbol))
                row["source"]="ROBINHOOD_POLL_FALLBACK"
                observations.append(row)
                broker_observations.append(row)
        except (RobinhoodUnavailable,ValueError,TypeError,KeyError):
            continue
    result["coinbase_scanned_pairs"]=coinbase_used
    result["market_data_source"]=(
        "COINBASE_PUBLIC_WS" if coinbase_used and market.get("state")=="LIVE" else
        "COINBASE_RECENT_CACHE" if coinbase_used else "ROBINHOOD_POLL_FALLBACK")
    result["pairs_checked"]=len(batch)
    result["quotes_checked"]=len(observations)
    history=(history+[{"symbol":r["symbol"],"mid":r["mid"],"at":r["at"]}
                       for r in broker_observations])[-2400:]
    write_atomic(history_path,history)
    signal_candidates=[r for r in observations if r["technical_approved"]]
    def entry_score(row):
        try:
            return Decimal(str(row.get("momentum_pct") or 0))-Decimal("2")*Decimal(str(row.get("spread_pct") or 0))
        except (InvalidOperation,ValueError,TypeError):
            return Decimal("-999")
    signal_candidates=sorted(signal_candidates,key=entry_score,reverse=True)
    result["ranked_entry_candidates"]=[r["symbol"] for r in signal_candidates[:5]]
    result["last_signal"]=(signal_candidates[0]["symbol"]+": MOMENTUM_CANDIDATE"
                          if signal_candidates else
                          "NO_SIGNAL" if observations else "QUOTE_UNAVAILABLE")
    result["signal_diagnostics"]=" · ".join(
        r["symbol"]+" ["+r.get("source","unverified")+"]: "+r["signal"]+
        (" ("+str(r["momentum_pct"])+"% momentum, "+str(r["spread_pct"])+"% spread; "+
         r.get("signal_reason","reason unavailable")+")" if r.get("momentum_pct") is not None else
         " ("+r.get("signal_reason","reason unavailable")+")")
        for r in observations) or "No valid broker quotes"
    ranked_observations=sorted(
        [r for r in observations if r.get("momentum_pct") is not None],
        key=lambda r:float(r.get("momentum_pct") or -999),reverse=True)
    result["top_entry_observations"]=[{
        "symbol":r.get("symbol"),"signal":r.get("signal"),"momentum_pct":r.get("momentum_pct"),
        "spread_pct":r.get("spread_pct"),"source":r.get("source"),
        "signal_reason":r.get("signal_reason"),"trend_up":r.get("trend_up"),
        "history_points":r.get("history_points"),"history_span_seconds":r.get("history_span_seconds")}
        for r in ranked_observations[:5]]
    result["observations"]=len(observations)
    result["ai_review_status"]="NOT_INVOKED_NO_TECHNICAL_CANDIDATE"
    result["ai_reason"]="Ollama review requires a qualified technical candidate; no trade decision was requested"
    from local_ai_gateway import installed_models, _settings, LocalAIUnavailable
    try:
        _, configured_model=_settings()
        models=installed_models()
        result["ai_connection_status"]="READY" if configured_model in models else "MODEL_NOT_INSTALLED"
        result["ai_model"]=configured_model
    except (LocalAIUnavailable,OSError,ValueError,TypeError):
        result["ai_connection_status"]="UNAVAILABLE"

    from robinhood_order_journal import OrderJournal,UnreconciledOrder
    journal=OrderJournal(state)
    pending=journal.pending()
    account_rows=client.list_accounts()
    # Reconcile every bot journal account, including already-final orders.
    # This upgrades legacy rows with broker-reported fill price, quantity,
    # fee and timestamps so cost basis and realized P/L are not inferred.
    journal_accounts={row.get("account") for row in journal.load()["orders"]
                      if isinstance(row,dict) and isinstance(row.get("account"),str)}
    authorized={a.get("account_number") for a in account_rows if isinstance(a,dict)}
    for account_ref in journal_accounts & authorized:
        broker_rows=client.orders(account_ref)
        known_clients={row.get("client_order_id") for row in broker_rows if isinstance(row,dict)}
        # If a successful submission already gave us a Robinhood order UUID,
        # query it directly when bulk history has not surfaced it yet.
        for intent in journal.pending():
            if intent.get("account")!=account_ref or intent.get("client_order_id") in known_clients:
                continue
            broker_id=intent.get("broker_order_id")
            if not isinstance(broker_id,str):continue
            try:
                direct=client.order(account_ref,broker_id)
                if isinstance(direct,dict):broker_rows.append(direct)
            except (OSError,ValueError,TypeError,RobinhoodUnavailable):
                pass
        journal.reconcile(account_ref,broker_rows)
    pending=journal.pending()
    positions=journal.positions()
    result["bot_open_positions"]=len(positions)
    result["daily_realized_pnl_usd"]=str(journal.daily_realized_pnl(datetime.now(timezone.utc)))

    from robinhood_risk import preflight,RiskDenied
    from robinhood_policy import read_policy,PolicyError
    risk_check="NOT_CONFIGURED"
    policy_path=Path(state)/"robinhood"/"risk_policy.json"
    try:
        policy=read_policy(state)
        rows=client.list_accounts()
        selected=next((a for a in rows if isinstance(a,dict)
                       and a.get("account_number")==policy.get("account")),None)
        if selected is None:raise RiskDenied("Configured account not available")
        preflight(selected,policy,"BTC-USD","1","0",len(pending))
        risk_check="ACCOUNT_PREFLIGHT_PASSED_SIGNAL_NOT_CHECKED"
    except (FileNotFoundError,PolicyError):
        policy={"enabled":False}
    except (RiskDenied,ValueError,TypeError,KeyError,StopIteration) as exc:
        risk_check="BLOCKED_"+type(exc).__name__

    # Existing bot positions are managed before any new entry. A technical
    # reversal can only take profit after the configured hold/profit floor;
    # a cost-basis stop-loss may exit independently to reduce risk.
    stop_pct=Decimal(str(policy.get("stop_loss_pct","2"))) if isinstance(policy,dict) else Decimal("2")
    exit_candidates=[]
    seen=set()
    for row in observations:
        pos=positions.get(row.get("symbol"))
        if not pos:continue
        protective=False
        try:
            mid=Decimal(str(row.get("mid")))
            cost=Decimal(str(pos["average_unit_cost"]))
            protective=cost>0 and (mid/cost-1)*100<=-stop_pct
        except (InvalidOperation,ValueError,TypeError,KeyError):
            protective=False
        if protective or row.get("technical_exit") is True:
            candidate=dict(row)
            candidate["protective_stop_hint"]=protective
            exit_candidates.append(candidate);seen.add(row["symbol"])
    exit_candidates.sort(key=lambda r:(not r.get("protective_stop_hint",False),
                                       -(abs(float(r.get("momentum_pct") or 0)))))
    result["exit_candidate_symbol"]=exit_candidates[0]["symbol"] if exit_candidates else None
    result["exit_momentum_pct"]=exit_candidates[0].get("momentum_pct") if exit_candidates else None
    result["exit_spread_pct"]=exit_candidates[0].get("spread_pct") if exit_candidates else None
    result["exit_signal_reason"]=(
        "Position-management candidate: technical reversal or configured cost-basis stop-loss"
        if exit_candidates else "No managed position exit")
    result["execution_reason"]="No order evaluated"
    execution="NOT_ARMED"
    order_confirmed=False
    exit_attempted=False

    if exit_candidates and not journal.pending():
        exit_attempted=True
        from robinhood_order_pass import submit_sell_approved,OrderPassBlocked
        from robinhood_crypto_execution import RobinhoodCryptoTradingAdapter
        blocked=[]
        for target in exit_candidates[:5]:
            try:
                if policy.get("enabled") is not True:
                    raise OrderPassBlocked("Account live policy not enabled")
                trader=RobinhoodCryptoTradingAdapter.from_state_authorized(state,policy)
                receipt=submit_sell_approved(state,trader,policy,target)
                execution="SELL_ORDER_ACCEPTED" if receipt["broker_acknowledged"] else "SELL_SUBMITTED_UNCONFIRMED"
                prepared=receipt.get("prepared",{})
                result["execution_reason"]=(
                    prepared.get("exit_mode","EXIT")+" "+target["symbol"]+
                    "; estimated P/L "+str(prepared.get("estimated_pnl_pct","unknown"))+
                    "%, held "+str(prepared.get("held_minutes","unknown"))+
                    " min; broker acknowledged="+str(receipt["broker_acknowledged"]))
                result["last_signal"]=target["symbol"]+": "+prepared.get("exit_mode","EXIT_ORDER")
                if receipt["broker_acknowledged"]:
                    journal.reconcile(policy["account"],trader.orders(policy["account"]))
                    order_confirmed=any(row.get("client_order_id")==receipt["client_order_id"]
                        and row.get("status")=="filled" for row in journal.load()["orders"])
                break
            except (OSError,ValueError,KeyError,TypeError,
                    RobinhoodUnavailable,OrderPassBlocked,RiskDenied,
                    UnreconciledOrder) as exc:
                blocked.append(target.get("symbol","?")+": "+
                               (str(exc)[:180] if isinstance(exc,OrderPassBlocked) else type(exc).__name__))
        if execution=="NOT_ARMED":
            execution="SELL_BLOCKED_OrderPassBlocked"
            result["execution_reason"]=" | ".join(blocked[:3]) or "Managed exit blocked"

    approved_signal=None
    # Risk reduction takes precedence. Only consider new entries when there is
    # no current managed-position exit candidate.
    if not exit_candidates and signal_candidates:
        from ai_research import approve_entry,research_evidence
        reviews=[]
        outcomes=[]
        result["ai_candidate_reviews"]=[]
        for target in signal_candidates[:3]:
            began=time.monotonic()
            approved,reason=approve_entry(target["symbol"],datetime.now(timezone.utc))
            elapsed=round(time.monotonic()-began,3)
            evidence=research_evidence(target["symbol"],datetime.now(timezone.utc))
            category=ai_review_category(approved,reason)
            outcomes.append(category)
            reviews.append(target["symbol"]+": "+reason[:220])
            result["ai_candidate_reviews"].append({
                "symbol":target["symbol"],"outcome":category,
                "elapsed_seconds":elapsed,
                "model":evidence.get("model"),
                "model_inference_seconds":evidence.get("inference_seconds"),
                "classifier_model_source":evidence.get("classifier_model_source"),
                "reason":reason[:240]})
            if evidence.get("model"):
                result["ai_model"]=evidence["model"]
            result["ai_review_duration_seconds"]=round(
                sum(r["elapsed_seconds"] for r in result["ai_candidate_reviews"]),3)
            if approved:
                approved_signal=dict(target,ai_approved=True)
                result["ai_review_status"]="PASS"
                result["ai_reason"]=reason[:500]
                result["entry_candidate_symbol"]=target["symbol"]
                result["entry_momentum_pct"]=target.get("momentum_pct")
                result["last_signal"]=target["symbol"]+": PASS"
                break
        if approved_signal is None:
            result["ai_review_status"]=(outcomes[0] if len(set(outcomes))==1
                else "MIXED_AI_REJECTIONS")
            result["ai_reason"]=" | ".join(reviews)[:500]
            result["entry_candidate_symbol"]=signal_candidates[0]["symbol"]
            result["entry_momentum_pct"]=signal_candidates[0].get("momentum_pct")
        if any(x=="AI_UNAVAILABLE" for x in outcomes):
            result["ai_connection_status"]="MODEL_RESPONSE_UNAVAILABLE"
        elif any(x not in ("NEWS_EVIDENCE_MISSING","NEWS_FEED_UNAVAILABLE")
                 for x in outcomes):
            if result.get("ai_connection_status")=="READY":
                result["ai_connection_status"]="REVIEW_PERFORMED"
        elif result.get("ai_connection_status")=="READY":
            result["ai_connection_status"]="NOT_INVOKED_NO_RELEVANT_NEWS"

    if execution=="NOT_ARMED" and approved_signal is not None:
        try:
            from robinhood_order_pass import submit_approved,OrderPassBlocked
            from robinhood_crypto_execution import RobinhoodCryptoTradingAdapter
            if policy.get("enabled") is not True:
                raise OrderPassBlocked("Account live trading policy not enabled")
            trader=RobinhoodCryptoTradingAdapter.from_state_authorized(state,policy)
            approved_signal=revalidate_buy_signal(state,trader,approved_signal)
            result["entry_signal_revalidated"]=approved_signal.get("ai_revalidated",False)
            receipt=submit_approved(state,trader,policy,approved_signal)
            execution="ORDER_ACCEPTED" if receipt["broker_acknowledged"] else "SUBMITTED_UNCONFIRMED"
            prepared=receipt.get("prepared",{})
            risk=prepared.get("risk",{})
            result["execution_reason"]=(
                "Ranked technical candidate + asset-specific AI approval; order "+
                str(prepared.get("notional","?"))+" USD; exposure before order "+
                str(risk.get("current_exposure_usd","?"))+" USD; broker acknowledged="+
                str(receipt["broker_acknowledged"]))
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
            result["execution_reason"]=str(exc)[:180] if isinstance(exc,OrderPassBlocked) else type(exc).__name__

    if execution=="NOT_ARMED":
        if exit_attempted:
            result["execution_reason"]=result.get("execution_reason","Managed exit did not submit")
        elif exit_candidates and signal_candidates:
            result["ai_review_status"]="NOT_INVOKED_POSITION_MANAGEMENT_PRIORITY"
            result["ai_reason"]="Entry AI review skipped because an existing bot position had a higher-priority exit evaluation"
            result["execution_reason"]="Entry candidate deferred while managed-position exit evaluation had priority"
        elif signal_candidates and approved_signal is None:
            result["execution_reason"]="Technical candidates were AI-reviewed; news gate approved none"
        else:
            result["execution_reason"]="No qualified technical entry or managed exit"

    positions=journal.positions()
    result.update({"risk_check":risk_check,"pending_order_intents":len(journal.pending()),
       "updated_at":datetime.now(timezone.utc).isoformat(),
       "worker":"monitoring",
       "execution_status":execution,
       "live_orders_allowed":execution in ("ORDER_ACCEPTED","SUBMITTED_UNCONFIRMED","SELL_ORDER_ACCEPTED","SELL_SUBMITTED_UNCONFIRMED"),
       "last_order_confirmed":order_confirmed,
       "bot_open_positions":len(positions),
       "daily_realized_pnl_usd":str(journal.daily_realized_pnl(datetime.now(timezone.utc))),
       "reason":"Orders require account risk approval, broker-confirmed fills, cost basis, and reconciliation"})
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
        "risk_check":result.get("risk_check"),
        "execution_reason":result.get("execution_reason"),
        "exit_candidate_symbol":result.get("exit_candidate_symbol"),
        "exit_momentum_pct":result.get("exit_momentum_pct"),
        "exit_spread_pct":result.get("exit_spread_pct"),
        "exit_signal_reason":result.get("exit_signal_reason"),
        "entry_candidate_symbol":result.get("entry_candidate_symbol"),
        "entry_momentum_pct":result.get("entry_momentum_pct"),
        "market_data_source":result.get("market_data_source"),
        "coinbase_feed":result.get("coinbase_feed"),
        "coinbase_live_pairs":result.get("coinbase_live_pairs"),
        "coinbase_scanned_pairs":result.get("coinbase_scanned_pairs"),
        "pairs_checked":result.get("pairs_checked"),
        "quotes_checked":result.get("quotes_checked"),
        "signal_diagnostics":result.get("signal_diagnostics"),
        "top_entry_observations":result.get("top_entry_observations"),
        "ranked_entry_candidates":result.get("ranked_entry_candidates"),
        "ai_candidate_reviews":result.get("ai_candidate_reviews",[]),
        "ai_review_duration_seconds":result.get("ai_review_duration_seconds"),
        "entry_signal_revalidated":result.get("entry_signal_revalidated")})
    write_atomic(evidence_path,evidence[-100:])
    return result

def main():
    state=Path(os.getenv("STATE_DIR","/state"))
    from coinbase_market_feed import CoinbaseFeed
    feed=CoinbaseFeed(state)
    feed.start()
    while True:
        try:
            client=RobinhoodCryptoAdapter.from_state(state)
            report=run_once(state,client,feed=feed)
            print("Robinhood monitoring:",report["quotes_checked"],"quote responses",flush=True)
        except (OSError,ValueError,KeyError,TypeError,RobinhoodUnavailable) as exc:
            write_atomic(state/"robinhood"/"worker_status.json",{
                "updated_at":datetime.now(timezone.utc).isoformat(),"worker":"blocked",
                "execution_status":"NOT_ARMED","live_orders_allowed":False,
                "last_order_confirmed":False,"reason":"Broker monitoring unavailable: "+type(exc).__name__})
        time.sleep(60)

if __name__=="__main__":main()
