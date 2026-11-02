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
    if symbol not in ("BTC-USD","ETH-USD","SOL-USD","DOGE-USD"):
        raise OrderPassBlocked("Crypto pair not in approved universe")
    accounts=client.list_accounts()
    matched=[a for a in accounts if isinstance(a,dict) and a.get("account_number")==policy.get("account")]
    if len(matched)!=1:raise OrderPassBlocked("Configured Robinhood account missing")
    account=matched[0]
    journal=OrderJournal(state)
    if journal.pending():raise OrderPassBlocked("Unresolved order intent")
    orders=client.orders(account["account_number"])
    if not isinstance(orders,list):raise OrderPassBlocked("Broker order history unavailable")
    if any(o.get("state") in ("open","pending") for o in orders if isinstance(o,dict)):
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
    min_qty=money(metadata.get("min_order_size",metadata.get("min_order_quantity",0)))
    increment=money(metadata.get("quantity_increment",metadata.get("asset_increment",0)))
    if min_qty<=0 or increment<=0:raise OrderPassBlocked("Asset size increments unverified")
    price=ask
    budget=money(risk["budget_usd"])
    qty=(budget/price/increment).to_integral_value(rounding=ROUND_DOWN)*increment
    if qty<min_qty or qty*price>budget:raise OrderPassBlocked("Order does not meet verified size limits")
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
