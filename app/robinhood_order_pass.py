"""Robinhood order pass: strict approved-signal to signed broker order boundary.

Never self-arms or fabricates signals. A failed/unknown POST retains the
durable intent to prevent duplicate automatic retries.
"""
from datetime import datetime,timezone
from decimal import Decimal,ROUND_DOWN
from uuid import uuid4
from robinhood_order_journal import OrderJournal,UnreconciledOrder
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

def review_order(state,client,policy,signal,now=None):
    """Independent checks, no submission. Use same result for test and live path."""
    now=now or datetime.now(timezone.utc)
    if not isinstance(signal,dict) or signal.get("technical_approved") is not True or signal.get("ai_approved") is not True:
        raise OrderPassBlocked("Approved technical and AI decisions required")
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
    # Broker metadata must independently establish that this pair is tradable.
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
    if qty<=0 or qty>max_qty or qty*price<minimum_usd or qty*price>budget:
        raise OrderPassBlocked("Order does not meet verified size limits")
    return {"account":account["account_number"],"symbol":symbol,
      "quantity":str(qty),"limit_price":str(price),
      "notional":str(qty*price),"risk":risk}

def submit_approved(state,client,policy,signal,now=None):
    """Never called by the monitoring worker; valid live worker must opt in."""
    prepared=review_order(state,client,policy,signal,now)
    order_id=str(uuid4())
    journal=OrderJournal(state)
    journal.record_intent(prepared["account"],order_id,
                         prepared["symbol"],prepared["quantity"],prepared["limit_price"])
    # On timeout or failure, do not delete intent or auto-resubmit.
    result=client.submit_order(prepared["account"],{
        "type":"limit","side":"buy","symbol":prepared["symbol"],
        "asset_quantity":prepared["quantity"],"limit_price":prepared["limit_price"],
        "client_order_id":order_id,"risk_approved":True,"operator_approved":True})
    return {"client_order_id":order_id,"broker_acknowledged":isinstance(result,dict) and bool(result.get("id")),
            "fill_verified":False}

def review_sell(state,client,policy,signal,now=None):
    """Exit decision for existing holdings only; never opens a short position."""
    now=now or datetime.now(timezone.utc)
    if not isinstance(signal,dict) or signal.get("technical_exit") is not True:
        raise OrderPassBlocked("Validated exit signal required")
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
    # Do not liquidate manually held Robinhood assets. Only filled buys placed
    # by this bot, minus filled bot sells, are eligible to be reduced.
    rows=journal.load()["orders"]
    bot_quantity=Decimal("0")
    for row in rows:
        if row.get("symbol")!=symbol or row.get("status")!="filled":continue
        side=row.get("side","buy")
        if side=="buy":bot_quantity+=money(row.get("quantity"))
        elif side=="sell":bot_quantity-=money(row.get("quantity"))
    if bot_quantity<=0:raise OrderPassBlocked("No bot-acquired holding available to sell")
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
    max_notional=money(policy.get("max_order_usd",0))
    if not 0<max_notional<=Decimal("25"):
        raise OrderPassBlocked("Account sell limit invalid")
    permitted=min(available,bot_quantity,max_qty,max_notional/bid)
    qty=(permitted/increment).to_integral_value(rounding=ROUND_DOWN)*increment
    if qty<=0 or qty>available or qty*bid<minimum:
        raise OrderPassBlocked("Sell order below minimum or unavailable")
    return {"account":account,"symbol":symbol,"quantity":str(qty),
        "limit_price":str(bid),"notional":str(qty*bid)}

def submit_sell_approved(state,client,policy,signal,now=None):
    prepared=review_sell(state,client,policy,signal,now)
    order_id=str(uuid4())
    journal=OrderJournal(state)
    journal.record_intent(prepared["account"],order_id,prepared["symbol"],
                          prepared["quantity"],prepared["limit_price"],side="sell")
    result=client.submit_order(prepared["account"],{
        "type":"limit","side":"sell","symbol":prepared["symbol"],
        "asset_quantity":prepared["quantity"],"limit_price":prepared["limit_price"],
        "client_order_id":order_id,"risk_approved":True,"operator_approved":True})
    return {"client_order_id":order_id,
        "broker_acknowledged":isinstance(result,dict) and bool(result.get("id")),
        "fill_verified":False}
