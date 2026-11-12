"""Robinhood order pass: approved signals to signed broker orders with position risk."""
from datetime import datetime,timezone
from decimal import Decimal,ROUND_DOWN
from uuid import uuid4
from robinhood_order_journal import OrderJournal,UnreconciledOrder
from robinhood_crypto_execution import RobinhoodWriteRejected
from robinhood_risk import preflight,RiskDenied,money

class OrderPassBlocked(RuntimeError):pass

def _quote_prices(response,symbol):
    rows=response.get("results") if isinstance(response,dict) else None
    if not isinstance(rows,list):raise OrderPassBlocked("Broker quote list missing")
    match=[r for r in rows if isinstance(r,dict) and r.get("symbol")==symbol]
    if len(match)!=1:raise OrderPassBlocked("Fresh matching broker quote missing")
    bid,ask=money(match[0].get("bid")),money(match[0].get("ask"))
    if bid<=0 or ask<bid:raise OrderPassBlocked("Invalid two-sided quote")
    return bid,ask

def _positive_policy(policy,key,default):
    value=money(policy.get(key,default))
    if value<=0:raise OrderPassBlocked(key+" must be positive")
    return value

def _integer_policy(policy,key,default,low,high):
    value=policy.get(key,default)
    if isinstance(value,bool):raise OrderPassBlocked(key+" invalid")
    try:value=int(value)
    except (ValueError,TypeError):raise OrderPassBlocked(key+" invalid") from None
    if not low<=value<=high:raise OrderPassBlocked(key+" outside permitted range")
    return value

def _current_exposure(client,positions,current_symbol,current_bid):
    total=Decimal("0")
    for symbol,position in positions.items():
        if position.get("cost_basis_verified") is not True:
            raise OrderPassBlocked("Bot position cost basis is not broker-verified")
        qty=position["quantity"]
        bid=current_bid if symbol==current_symbol else _quote_prices(client.quote(symbol),symbol)[0]
        total+=qty*bid
    return total

def review_order(state,client,policy,signal,now=None):
    """Independent buy checks. No submission occurs here."""
    now=now or datetime.now(timezone.utc)
    if not isinstance(signal,dict) or signal.get("technical_approved") is not True:
        raise OrderPassBlocked("Qualified technical signal required")
    ai_approved=signal.get("ai_approved") is True
    no_news_approved=(signal.get("news_optional_technical_approved") is True
        and signal.get("news_evidence_status")=="NO_RELEVANT_HEADLINES"
        and signal.get("ai_approved") is False)
    if no_news_approved:
        # No-news entries have NO AI endorsement. Require the original
        # technical momentum, coverage, and spread limits explicitly.
        try:
            momentum=Decimal(str(signal["momentum_pct"]))
            spread_pct=Decimal(str(signal["spread_pct"]))
            span=Decimal(str(signal["history_span_seconds"]))
            points=int(signal["history_points"])
        except (KeyError,ValueError,TypeError,ArithmeticError):
            raise OrderPassBlocked("No-news technical proof incomplete") from None
        if not (momentum.is_finite() and spread_pct.is_finite() and span.is_finite()
                and Decimal("0.5")<=momentum<=Decimal("2")
                and Decimal("0")<=spread_pct<=Decimal("0.5")
                and span>=Decimal("300") and points>=4
                and signal.get("trend_up") is True
                and signal.get("signal")=="MOMENTUM_CANDIDATE"):
            raise OrderPassBlocked("No-news technical proof did not meet entry rules")
    if not ai_approved and not no_news_approved:
        raise OrderPassBlocked("Validated AI approval or verified news-optional technical approval required")
    at=signal.get("at")
    try:age=(now-datetime.fromisoformat(at.replace("Z","+00:00"))).total_seconds()
    except (ValueError,TypeError,AttributeError):raise OrderPassBlocked("Signal timestamp invalid") from None
    if age<0 or age>90:raise OrderPassBlocked("Signal is stale")
    symbol=signal.get("symbol")
    from robinhood_crypto_gateway import PAIR
    if not isinstance(symbol,str) or not PAIR.fullmatch(symbol):
        raise OrderPassBlocked("Invalid USD trading pair")
    accounts=client.list_accounts()
    matched=[a for a in accounts if isinstance(a,dict) and a.get("account_number")==policy.get("account")]
    if len(matched)!=1:raise OrderPassBlocked("Configured Robinhood account missing")
    account=matched[0]
    journal=OrderJournal(state)
    if journal.pending():raise OrderPassBlocked("Unresolved order intent")
    orders=client.orders(account["account_number"])
    if not isinstance(orders,list):raise OrderPassBlocked("Broker order history unavailable")
    if any(o.get("state") in ("open","pending","partially_filled") for o in orders if isinstance(o,dict)):
        raise OrderPassBlocked("Existing Robinhood order still open")
    bid,ask=_quote_prices(client.quote(symbol),symbol)
    spread=(ask-bid)/ask*100
    risk=preflight(account,policy,symbol,ask,spread)
    pairs=client.trading_pairs()
    matched_pairs=[p for p in pairs if isinstance(p,dict) and p.get("symbol")==symbol]
    if len(matched_pairs)!=1 or matched_pairs[0].get("is_api_tradable") is not True:
        raise OrderPassBlocked("Tradable pair not verified")
    metadata=matched_pairs[0]
    increment=money(metadata.get("asset_increment",0))
    minimum_usd=money(metadata.get("min_order_amount",0))
    max_qty=money(metadata.get("max_order_size",0))
    if minimum_usd<=0 or increment<=0 or max_qty<=0:
        raise OrderPassBlocked("Broker increments and minimum amount unverified")
    price=ask
    budget=money(risk["budget_usd"])
    qty=(budget/price/increment).to_integral_value(rounding=ROUND_DOWN)*increment
    notional=qty*price
    if qty<=0 or qty>max_qty or notional<minimum_usd or notional>budget:
        raise OrderPassBlocked("Order does not meet verified size limits")

    daily=journal.daily_realized_pnl(now)
    daily_limit=_positive_policy(policy,"max_daily_loss_usd","5")
    if daily<=-daily_limit:
        raise OrderPassBlocked("Daily realized loss limit reached: "+str(daily)+" USD")

    positions=journal.positions()
    max_positions=_integer_policy(policy,"max_open_positions",3,1,10)
    if symbol not in positions and len(positions)>=max_positions:
        raise OrderPassBlocked("Maximum bot open positions reached")
    cooldown=_integer_policy(policy,"reentry_cooldown_minutes",30,0,1440)
    last_exit=journal.last_exit_at(symbol)
    if last_exit is not None and symbol not in positions:
        minutes=(now-last_exit.astimezone(now.tzinfo)).total_seconds()/60
        if 0<=minutes<cooldown:
            raise OrderPassBlocked("Re-entry cooldown active for "+symbol)
    exposure=_current_exposure(client,positions,symbol,bid)
    max_exposure=_positive_policy(policy,"max_total_exposure_usd","25")
    if exposure+notional>max_exposure:
        raise OrderPassBlocked("Maximum bot crypto exposure would be exceeded")
    asset_cap_pct=_positive_policy(policy,"max_single_asset_exposure_pct","60")
    if asset_cap_pct>Decimal("100"):
        raise OrderPassBlocked("Single-asset exposure percentage invalid")
    already=positions[symbol]["quantity"]*bid if symbol in positions else Decimal("0")
    if already+notional>max_exposure*asset_cap_pct/Decimal("100"):
        raise OrderPassBlocked("Single-asset exposure limit would be exceeded")
    if symbol in positions:
        add_interval=_integer_policy(policy,"min_add_interval_minutes",30,0,1440)
        if add_interval>0:
            previous=[]
            for row in journal.load()["orders"]:
                if row.get("symbol")!=symbol or row.get("side")!="buy" or row.get("status")!="filled":
                    continue
                try:
                    filled=datetime.fromisoformat(row["filled_at"].replace("Z","+00:00"))
                    if filled.tzinfo is not None:previous.append(filled.astimezone(timezone.utc))
                except (ValueError,TypeError,KeyError,AttributeError):pass
            if previous:
                age=(now-max(previous)).total_seconds()/60
                if age<0 or age<add_interval:
                    raise OrderPassBlocked("Additional buy cooldown active for "+symbol)
    from robinhood_entry_quality import verify_entry,EntryQualityBlocked
    try:
        quality=verify_entry(policy,signal,spread,journal,now)
    except EntryQualityBlocked as exc:
        raise OrderPassBlocked(str(exc)) from None
    risk["entry_quality"]=quality
    risk.update({"daily_realized_pnl_usd":str(daily),"current_exposure_usd":str(exposure),
                 "open_positions":len(positions),"max_total_exposure_usd":str(max_exposure),
                 "symbol_exposure_usd":str(already),"max_symbol_exposure_usd":
                 str(max_exposure*asset_cap_pct/Decimal("100"))})
    return {"account":account["account_number"],"symbol":symbol,
      "quantity":str(qty),"limit_price":str(price),
      "notional":str(notional),"risk":risk}

def submit_approved(state,client,policy,signal,now=None):
    prepared=review_order(state,client,policy,signal,now)
    order_id=str(uuid4())
    journal=OrderJournal(state)
    journal.record_intent(prepared["account"],order_id,
                         prepared["symbol"],prepared["quantity"],prepared["limit_price"])
    try:
        result=client.submit_order(prepared["account"],{
            "type":"limit","side":"buy","symbol":prepared["symbol"],
            "asset_quantity":prepared["quantity"],"limit_price":prepared["limit_price"],
            "client_order_id":order_id,"risk_approved":True,"operator_approved":True})
    except RobinhoodWriteRejected as exc:
        journal.mark_submission_rejected(order_id,str(exc))
        raise
    journal.mark_submission_ack(order_id,result if isinstance(result,dict) else {})
    return {"client_order_id":order_id,"broker_order_id":result.get("id") if isinstance(result,dict) else None,
            "broker_acknowledged":isinstance(result,dict) and bool(result.get("id")),
            "fill_verified":False,"prepared":prepared}

def review_sell(state,client,policy,signal,now=None):
    """Allow profit-protecting technical exits or an explicit cost-basis stop loss."""
    now=now or datetime.now(timezone.utc)
    if not isinstance(signal,dict):raise OrderPassBlocked("Exit candidate missing")
    try:
        age=(now-datetime.fromisoformat(signal["at"].replace("Z","+00:00"))).total_seconds()
    except (KeyError,ValueError,TypeError,AttributeError):
        raise OrderPassBlocked("Invalid exit timestamp") from None
    if not 0<=age<=90:raise OrderPassBlocked("Exit signal stale")
    from robinhood_crypto_gateway import PAIR
    symbol=signal.get("symbol")
    if not isinstance(symbol,str) or not PAIR.fullmatch(symbol):
        raise OrderPassBlocked("Invalid USD pair")
    if policy.get("enabled") is not True:raise OrderPassBlocked("Trading permission disabled")
    accounts=[a for a in client.list_accounts() if isinstance(a,dict)
              and a.get("account_number")==policy.get("account")
              and a.get("is_api_tradable") is True and a.get("status")=="active"]
    if len(accounts)!=1:raise OrderPassBlocked("Trading account not verified")
    account=accounts[0]["account_number"]
    journal=OrderJournal(state)
    if journal.pending():raise OrderPassBlocked("Unresolved order intent")
    bot=journal.positions().get(symbol)
    if not bot or bot["quantity"]<=0:raise OrderPassBlocked("No bot-acquired holding available to sell")
    if bot.get("cost_basis_verified") is not True:
        raise OrderPassBlocked("Broker-verified cost basis unavailable")
    orders=client.orders(account)
    if not isinstance(orders,list) or any(isinstance(o,dict) and o.get("state") in
            ("open","pending","partially_filled") for o in orders):
        raise OrderPassBlocked("Pending broker order or order history unavailable")
    matches=[p for p in client.trading_pairs() if isinstance(p,dict)
        and p.get("symbol")==symbol and p.get("is_api_tradable") is True]
    if len(matches)!=1:raise OrderPassBlocked("Pair not broker tradable")
    metadata=matches[0]
    increment=money(metadata.get("asset_increment",0))
    minimum=money(metadata.get("min_order_amount",0))
    max_qty=money(metadata.get("max_order_size",0))
    if increment<=0 or minimum<=0 or max_qty<=0:
        raise OrderPassBlocked("Broker sell constraints unverified")
    rows=[h for h in client.positions(account) if isinstance(h,dict)
          and h.get("asset_code")==symbol.removesuffix("-USD")]
    if len(rows)!=1:raise OrderPassBlocked("Owned asset unavailable")
    available=money(rows[0].get("quantity_available_for_trading"))
    if available<=0:raise OrderPassBlocked("No available holding to sell")
    bid,ask=_quote_prices(client.quote(symbol),symbol)
    spread=(ask-bid)/ask*100
    if spread>Decimal("0.5"):raise OrderPassBlocked("Excessive sell spread")

    unit_cost=bot["average_unit_cost"]
    from robinhood_fee_estimates import effective_sell_fee_pct
    try:
        fee_buffer,fee_source=effective_sell_fee_pct(policy,journal)
    except ValueError:
        raise OrderPassBlocked("Fee buffer unavailable") from None
    estimated_net_unit=bid*(Decimal("1")-fee_buffer/Decimal("100"))
    pnl_pct=(estimated_net_unit/unit_cost-Decimal("1"))*Decimal("100")
    legacy_buffer=money(policy.get("fee_buffer_pct","0.25"))
    stop_reference_pct=((bid*(Decimal("1")-legacy_buffer/Decimal("100"))/unit_cost)
                        -Decimal("1"))*Decimal("100")
    stop_loss=_positive_policy(policy,"stop_loss_pct","2")
    min_profit=_positive_policy(policy,"min_profit_pct","1")
    min_hold=_integer_policy(policy,"min_hold_minutes",15,1,1440)
    opened_at=bot.get("opened_at")
    try:opened=datetime.fromisoformat(opened_at.replace("Z","+00:00"))
    except (ValueError,TypeError,AttributeError):raise OrderPassBlocked("Position open time unavailable") from None
    held_minutes=max(Decimal("0"),Decimal(str((now-opened.astimezone(now.tzinfo)).total_seconds()/60)))
    technical_exit=signal.get("technical_exit") is True
    # Maintain pre-existing stop-loss firing boundary; the more accurate
    # broker fee reserve is for profit qualification, not premature stop-outs.
    stop_hit=stop_reference_pct<=-stop_loss
    hold_met=held_minutes>=min_hold
    take_profit=_positive_policy(policy,"take_profit_pct","3.0")
    trailing_activation=_positive_policy(policy,"trailing_activation_pct","2.0")
    trailing_drawdown=_positive_policy(policy,"trailing_drawdown_pct","0.75")
    if take_profit<min_profit or trailing_activation<min_profit+trailing_drawdown:
        raise OrderPassBlocked("Invalid take-profit/trailing thresholds")
    target_hit=hold_met and pnl_pct>=take_profit
    peak_bid=None
    peak_pnl_pct=None
    peak_drawdown_pct=None
    trailing_hit=False
    if hold_met and not stop_hit and not target_hit:
        from robinhood_exit_tracker import ExitTracker,ExitTrackerError
        try:
            peak_bid=ExitTracker(state).peak(account,symbol,bot)
        except (ExitTrackerError,OSError):
            peak_bid=None
        if peak_bid is not None:
            peak_net=peak_bid*(Decimal("1")-fee_buffer/Decimal("100"))
            peak_pnl_pct=(peak_net/unit_cost-Decimal("1"))*Decimal("100")
            peak_drawdown_pct=max(Decimal("0"),(Decimal("1")-bid/peak_bid)*Decimal("100"))
            trailing_hit=(peak_pnl_pct>=trailing_activation
                          and peak_drawdown_pct>=trailing_drawdown
                          and pnl_pct>=min_profit)
    profitable_reversal=technical_exit and hold_met and pnl_pct>=min_profit
    if stop_hit:exit_mode="STOP_LOSS"
    elif target_hit:exit_mode="TAKE_PROFIT"
    elif trailing_hit:exit_mode="TRAILING_PROFIT"
    elif profitable_reversal:exit_mode="PROFIT_REVERSAL"
    else:
        raise OrderPassBlocked(
            "Exit blocked: estimated P/L "+str(pnl_pct.quantize(Decimal("0.01")))+
            "%; take-profit >="+str(take_profit)+"% or trailing gain protection "
            "or technical reversal >="+str(min_profit)+"% after "+
            str(min_hold)+" min, or stop-loss <=-"+str(stop_loss)+"%")

    max_notional=money(policy.get("max_order_usd",0))
    if not 0<max_notional<=Decimal("25"):
        raise OrderPassBlocked("Account sell limit invalid")
    permitted=min(available,bot["quantity"],max_qty,max_notional/bid)
    qty=(permitted/increment).to_integral_value(rounding=ROUND_DOWN)*increment
    if qty<=0 or qty>available or qty*bid<minimum:
        raise OrderPassBlocked("Sell order below minimum or unavailable")
    estimated_pnl=(estimated_net_unit-unit_cost)*qty
    return {"account":account,"symbol":symbol,"quantity":str(qty),
        "limit_price":str(bid),"notional":str(qty*bid),"exit_mode":exit_mode,
        "estimated_pnl_pct":str(pnl_pct),"estimated_pnl_usd":str(estimated_pnl),
        "average_unit_cost":str(unit_cost),"held_minutes":str(held_minutes),
        "fee_buffer_pct":str(fee_buffer),
        "fee_buffer_source":fee_source,
        "take_profit_target_pct":str(take_profit),
        "trailing_activation_pct":str(trailing_activation),
        "trailing_drawdown_pct":str(trailing_drawdown),
        "peak_bid":str(peak_bid) if peak_bid is not None else None,
        "peak_net_pnl_pct":str(peak_pnl_pct) if peak_pnl_pct is not None else None,
        "peak_retracement_pct":str(peak_drawdown_pct) if peak_drawdown_pct is not None else None}

def submit_sell_approved(state,client,policy,signal,now=None):
    prepared=review_sell(state,client,policy,signal,now)
    order_id=str(uuid4())
    journal=OrderJournal(state)
    journal.record_intent(prepared["account"],order_id,prepared["symbol"],
                          prepared["quantity"],prepared["limit_price"],side="sell")
    try:
        result=client.submit_order(prepared["account"],{
            "type":"limit","side":"sell","symbol":prepared["symbol"],
            "asset_quantity":prepared["quantity"],"limit_price":prepared["limit_price"],
            "client_order_id":order_id,"risk_approved":True,"operator_approved":True})
    except RobinhoodWriteRejected as exc:
        journal.mark_submission_rejected(order_id,str(exc))
        raise
    journal.mark_submission_ack(order_id,result if isinstance(result,dict) else {})
    return {"client_order_id":order_id,"broker_order_id":result.get("id") if isinstance(result,dict) else None,
        "broker_acknowledged":isinstance(result,dict) and bool(result.get("id")),
        "fill_verified":False,"prepared":prepared}
