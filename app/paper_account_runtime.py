"""Paper account execution using the SAME shared scan and AI gate as Schwab.

Only the adapter changes the paper_account.json virtual balance and positions.
No code in this module submits an order to a real brokerage.
"""
from datetime import datetime,timezone
from decimal import Decimal,ROUND_DOWN
from pathlib import Path
from paper_broker_adapter import PaperBrokerAdapter
from shared_strategy import select_entry
from autonomous_selector import UNIVERSE
from live_order_safety import cross_signal,quote_levels
from dashboard_control import read_control
from ai_research import approve_entry

def _checked_json(response):
    if response.status_code!=200:raise ValueError("Read-only market data unavailable")
    doc=response.json()
    if not isinstance(doc,dict):raise ValueError("Invalid quote response")
    return doc

def paper_quote(client,symbol,now):
    from datetime import datetime,timezone
    q=_checked_json(client.get_quotes([symbol]))[symbol]["quote"]
    bid,ask=quote_levels({"quote":q},now)
    return {"symbol":symbol,"bid":float(bid),"ask":float(ask),
            "price":float(ask),"timestamp":datetime.fromtimestamp(
                int(q["quoteTime"])/1000,timezone.utc).isoformat()}

def paper_tick(client,state_dir,now=None,approve=approve_entry):
    """One controlled strategy tick. Return a decision, never brokerage orders."""
    now=now or datetime.now(timezone.utc)
    state_dir=Path(state_dir)
    control=read_control(state_dir/"control.json")
    if control["mode"]!="running":return {"decision":"PAUSED"}
    options=control["settings"]
    import os
    adapter=PaperBrokerAdapter(state_dir,
        initial_cash=os.getenv("PAPER_INITIAL_CAPITAL","100"),
        quote_provider=lambda sym:paper_quote(client,sym,now))
    ref=adapter.account_ref
    existing=adapter.positions(ref)
    positions={p["symbol"]:p for p in existing}
    for symbol,pos in positions.items():
        if symbol not in UNIVERSE:continue
        candles=_checked_json(client.get_price_history_every_five_minutes(
            symbol,need_extended_hours_data=False))["candles"]
        signal,candle=cross_signal(candles,now)
        if signal=="SELL":
            qty=Decimal(str(pos["quantity"]))
            if qty>0:
                fill=adapter.submit_order(ref,{"symbol":symbol,"side":"SELL",
                    "quantity":str(qty),"client_order_id":f"{symbol}-{candle}-SELL"})
                return {"decision":"PAPER_SELL","order":fill}
    snapshot=adapter._read()
    cash_now=Decimal(str(snapshot["cash"]))
    account_equity=cash_now+sum(
        Decimal(str(pos["quantity"]))*Decimal(str(pos["entry_price"]))
        for pos in snapshot["positions"].values())
    today=now.astimezone(timezone.utc).date().isoformat()
    if snapshot.get("day")!=today:
        snapshot["day"]=today
        snapshot["day_start_equity"]=float(account_equity)
        adapter._save(snapshot)
    if Decimal(str(snapshot.get("day_start_equity",account_equity)))-account_equity >= Decimal(str(options["max_daily_loss"])):
        return {"decision":"DAILY_LOSS_LIMIT"}
    if len(positions)>=int(options["max_open_positions"]):
        return {"decision":"POSITION_LIMIT"}
    quotes=_checked_json(client.get_quotes(list(UNIVERSE)))
    def candles_for(symbol):
        return _checked_json(client.get_price_history_every_five_minutes(
            symbol,need_extended_hours_data=False))["candles"]
    candidate,ranked=select_entry(quotes,candles_for,now,excluded=positions)
    if candidate is None:return {"decision":"NO_SIGNAL","considered":len(ranked)}
    accepted,reason=approve(candidate.symbol,now)
    if not accepted:
        adapter.record_review(candidate.symbol,now,"VETO",reason)
        return {"decision":"AI_VETO","symbol":candidate.symbol,"reason":reason}
    cash=Decimal(adapter.balances(ref)["cash"])
    budget=min(cash*Decimal(str(options["allocation_pct"]))/100,
               Decimal(str(options["max_order_usd"])) if options["max_order_usd"]>0 else cash,
               (cash+sum(Decimal(str(p["quantity"]))*Decimal(str(p["entry_price"]))
                  for p in positions.values()))*Decimal(str(options["max_position_pct"]))/100)
    qty=(budget/candidate.ask).to_integral_value(rounding=ROUND_DOWN)
    if qty<1:return {"decision":"INSUFFICIENT_CASH","symbol":candidate.symbol}
    fill=adapter.submit_order(ref,{"symbol":candidate.symbol,"side":"BUY",
                "quantity":str(qty),"client_order_id":f"{candidate.symbol}-{candidate.candle}-BUY"})
    adapter.record_review(candidate.symbol,now,"APPROVED",reason)
    return {"decision":"PAPER_BUY","order":fill}
def paper_main(run=True):
    """Run the paper account through live_worker.py, never a second bot engine."""
    import json,logging,os,time
    from dashboard_control import write_atomic
    state=Path(os.getenv("STATE_DIR","/state"))
    logs=Path(os.getenv("LOG_DIR","/logs"))
    state.mkdir(parents=True,exist_ok=True)
    logs.mkdir(parents=True,exist_ok=True)
    logging.basicConfig(level=logging.INFO,handlers=[
        logging.StreamHandler(),logging.FileHandler(logs/"paper-account.log")],
        format="%(asctime)s %(levelname)s %(message)s")
    last_scan=0.0
    last_result={}
    while True:
        mode="stopped"
        error=""
        try:
            control=read_control(state/"control.json")
            mode=control["mode"]
            if mode=="running" and (not last_scan or time.monotonic()-last_scan>=300):
                last_scan=time.monotonic()
                # This client is used for market-data reads only. The paper
                # executor has no access to a brokerage order method.
                from live_worker import broker
                client=broker()
                last_result=paper_tick(client,state)
                logging.info("Shared strategy paper decision: %s; symbol=%s; reason=%s",last_result.get("decision"),last_result.get("symbol","-"),str(last_result.get("reason",""))[:160])
        except Exception as exc:
            error=type(exc).__name__
            logging.warning("Paper account scan unavailable: %s",error)
        try:
            adapter=PaperBrokerAdapter(state,initial_cash=os.getenv("PAPER_INITIAL_CAPITAL","100"))
            account=adapter.balances(adapter.account_ref)
            paper_state=adapter._read()
            equity=Decimal(account["cash"])+sum(
                Decimal(str(position["quantity"]))*Decimal(str(
                   paper_state.get("history",{}).get(symbol,[{"price":position["entry_price"]}])[-1]["price"]))
                for symbol,position in paper_state.get("positions",{}).items())
            control=read_control(state/"control.json")
            write_atomic(state/"runtime_status.json",{
                "updated_at":datetime.now(timezone.utc).isoformat(),
                "mode":mode,"paper_only":True,"last_error":error,
                "ai_model_configured":bool(os.getenv("LOCAL_AI_MODEL") and os.getenv("LOCAL_AI_URL")),
                "public_market_feed":False,
                "market_source":"schwab_read_only",
                "paper_quotes_available":last_result.get("considered",0),
                "paper_feed_checked_at":datetime.now(timezone.utc).isoformat() if last_result else None,
                 "cash":float(account["cash"]),"equity":float(equity),
                "trades":len(adapter.orders(adapter.account_ref)),
                "revision":control["revision"],
                "day_start_equity":float(paper_state.get("day_start_equity",equity)),
                "daily_growth_target_pct":control["settings"]["daily_growth_target_pct"],
                "daily_target_reached":False})
        except Exception as exc:
            logging.warning("Paper telemetry unavailable: %s",type(exc).__name__)
        if not run:return
        time.sleep(15)
