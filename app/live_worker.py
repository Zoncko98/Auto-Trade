"""Schwab LIVE trading worker. No automatic trading until explicit live activation.

Uses Schwab's actual account, positions, pending orders, market hours and quotes.
Only U.S. long equity/ETF day-limit orders; no margin, options or fractional orders.
One broker order at a time. Any ambiguity halts instead of retrying.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import tempfile
import sys
from urllib.parse import urlparse
import time
from datetime import datetime, timedelta, time as dtime, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from live_order_safety import (CAPITAL, DAILY_LOSS, LiveBlocked, OrderLedger,
    OPEN_STATUSES, TERMINAL, buy_quantity, cross_signal, equity_value,
    money, position_snapshot, quote_levels, sell_limit, verified_cash)
from autonomous_selector import UNIVERSE, ranked_candidates, choose_entry
from ai_research import approve_entry, research_evidence
from live_extension import (read_live_risk, broker_fills, log_decision)

CONFIG_PATH = Path(os.getenv("SCHWAB_ENV_FILE",
    str(Path.home() / ".config" / "auto-trader" / "schwab.env")))
TOKEN_PATH = Path(os.getenv("SCHWAB_TOKEN_FILE",
    str(Path.home() / ".config" / "auto-trader" / "schwab_token.json")))
STATE_DIR = Path(os.getenv("LIVE_STATE_DIR",
    str(Path.home() / ".config" / "auto-trader" / "live-state")))
JOURNAL = STATE_DIR / "orders.json"
MAX_CONCURRENT_POSITIONS = 3
MAX_DAILY_BUYS = 3
MAX_DAILY_ACTIONS = 7


def write_private_json(path, payload):
    """Atomic, owner-only telemetry; no credentials or account identifiers."""
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    raw=json.dumps(payload,allow_nan=False).encode("utf-8")
    fd,name=tempfile.mkstemp(prefix=".telemetry-",dir=path.parent)
    try:
        with os.fdopen(fd,"wb") as handle:
            os.fchmod(handle.fileno(),0o600)
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def operator_mode():
    """Missing or invalid GUI control means do not submit new orders."""
    try:
        obj=json.loads((STATE_DIR/"operator.json").read_text(encoding="utf-8"))
        return "running" if obj.get("version")==1 and obj.get("mode")=="running" else "paused"
    except (OSError,TypeError,ValueError):
        return "paused"


def write_heartbeat(armed, mode):
    write_private_json(STATE_DIR/"worker_heartbeat.json",{
        "at":datetime.now(timezone.utc).isoformat(),
        "armed":bool(armed),"mode":mode,
        "model":"local model selected through dashboard"
    })


def publish_account_snapshot(positions,exposure,cash,equity):
    write_private_json(STATE_DIR/"account_snapshot.json",{
        "at":datetime.now(timezone.utc).isoformat(),
        "positions":positions, "exposure":str(exposure),
        "cash":str(cash),"equity":str(equity)
    })


def private_file(path):
    if not path.is_file() or path.stat().st_mode & 0o077:
        raise LiveBlocked("Missing or insecure Schwab private file")
    return path


def config():
    data = {}
    for line in private_file(CONFIG_PATH).read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        if "=" not in line:
            raise LiveBlocked("Malformed Schwab configuration file")
        k, v = line.split("=",1)
        if k in data or k not in {"SCHWAB_APP_KEY","SCHWAB_APP_SECRET",
                                 "SCHWAB_CALLBACK_URL"}:
            raise LiveBlocked("Unexpected Schwab config field")
        data[k] = v.strip()
    if not data.get("SCHWAB_APP_KEY") or not data.get("SCHWAB_APP_SECRET"):
        raise LiveBlocked("Schwab app credentials not installed")
    cb=urlparse(data.get("SCHWAB_CALLBACK_URL",""))
    if cb.scheme!="https" or cb.hostname!="127.0.0.1" or not 1024<=int(cb.port or 0)<=65535 or cb.username or cb.password or cb.query or cb.fragment:
        raise LiveBlocked("Schwab callback must be the registered local HTTPS redirect")
    private_file(TOKEN_PATH)
    return data


def broker():
    from schwab.auth import client_from_token_file
    values = config()
    return client_from_token_file(str(TOKEN_PATH), values["SCHWAB_APP_KEY"],
                                  values["SCHWAB_APP_SECRET"])


def result(response, label):
    if response.status_code != 200:
        raise LiveBlocked(f"Schwab {label} unavailable (HTTP {response.status_code})")
    try:
        return response.json()
    except Exception:
        raise LiveBlocked(f"Malformed Schwab {label}") from None


def confirm_account(client, configured_hash):
    from schwab.client import Client
    refs = result(client.get_account_numbers(), "account mapping")
    if not isinstance(refs, list) or not refs:
        raise LiveBlocked("No authorized Schwab brokerage accounts")
    hashes = {x.get("hashValue") for x in refs if isinstance(x,dict)}
    if not configured_hash:
        if len(hashes) == 1:
            print("One Schwab account authorized; not selected for live orders yet.")
        else:
            print(f"{len(hashes)} Schwab accounts authorized; explicit account selection required.")
        raise LiveBlocked("LIVE_ACCOUNT_HASH must be pinned after reviewing broker account")
    if configured_hash not in hashes:
        raise LiveBlocked("Pinned brokerage account not authorized")
    account = result(client.get_account(
        configured_hash, fields=Client.Account.Fields.POSITIONS), "account and positions")
    if not isinstance(account, dict):
        raise LiveBlocked("Unexpected Schwab account response")
    position_snapshot(account)   # Reject unsupported or short positions, not account types.
    return account


def market_is_normal(client, now):
    from schwab.client import Client
    ny = now.astimezone(ZoneInfo("America/New_York"))
    if ny.weekday() > 4 or not dtime(9,35) <= ny.time() < dtime(15,55):
        return False
    market = result(client.get_market_hours(
        Client.MarketHours.Market.EQUITY, date=ny.date()), "market hours")
    # Stock market calendar and today's session are authoritative.
    if not isinstance(market,dict):
        raise LiveBlocked("Invalid market calendar")
    equity = market.get("equity")
    if not isinstance(equity, dict):
        raise LiveBlocked("Schwab equity market hours missing")
    return any(isinstance(row,dict) and row.get("isOpen") is True
               for row in equity.values())


def get_snapshot(client, account_hash):
    from schwab.client import Client
    acct = result(client.get_account(
        account_hash, fields=Client.Account.Fields.POSITIONS), "account")
    positions, exposure=position_snapshot(acct)
    cash=verified_cash(acct)
    equity=equity_value(acct)
    if cash < 0 or equity < 0:
        raise LiveBlocked("Invalid broker account values")
    publish_account_snapshot(positions,exposure,cash,equity)
    return acct, positions, exposure, cash, equity


def current_broker_orders(client, account_hash):
    raw = result(client.get_orders_for_account(account_hash, max_results=100),
                 "order history")
    if not isinstance(raw, list):
        raise LiveBlocked("Malformed Schwab order history")
    if len(raw)>=100:
        raise LiveBlocked("Broker order history reached request limit; cannot guarantee reconciliation")
    return raw


def broker_order_id(item):
    oid=item.get("orderId")
    if isinstance(oid, (int, str)) and str(oid).isdigit():
        return str(oid)
    raise LiveBlocked("Broker order missing ID")


def reconcile(client, account_hash, ledger):
    orders = current_broker_orders(client, account_hash)
    known = {x.get("order_id") for x in ledger.data["orders"] if x.get("order_id")}
    for order in orders:
        if not isinstance(order,dict):
            raise LiveBlocked("Malformed broker order")
        status=order.get("status")
        if status not in TERMINAL | OPEN_STATUSES:
            raise LiveBlocked("Unknown Schwab order status; review required")
        order_id=broker_order_id(order)
        if order_id not in known:
            if status in OPEN_STATUSES:
                raise LiveBlocked("External or unknown live order is open")
            # An external completed order after baseline adoption can change
            # settled cash and position ownership without our ledger knowing.
            adopted=ledger.data.get("opening_inventory_adopted")
            entered=order.get("enteredTime")
            if not adopted or not isinstance(entered,str):
                raise LiveBlocked("Untracked broker order has no reliable baseline")
            try:
                entered_at=datetime.fromisoformat(entered.replace("Z","+00:00"))
                baseline=datetime.fromisoformat(adopted)
                if entered_at.tzinfo is None:
                    raise ValueError("Missing timezone")
            except (TypeError, ValueError):
                raise LiveBlocked("Untracked broker order date cannot be verified") from None
            if entered_at>=baseline:
                raise LiveBlocked("External filled order after bot activation; reconcile")
    for local in ledger.data["orders"]:
        if local.get("state") in ("SUBMITTING","UNKNOWN"):
            ledger.halt("Submission result unknown: manually reconcile with Schwab")
            raise LiveBlocked("Unknown order submission outcome; cannot retry")
        if local.get("state") == "ACCEPTED":
            remote = result(client.get_order(int(local["order_id"]), account_hash),
                            "single order status")
            status=remote.get("status")
            if status in TERMINAL:
                filled=money(remote.get("filledQuantity",0), "filled quantity")
                if status=="FILLED" and filled!=Decimal(local["quantity"]):
                    ledger.halt("Fill quantity discrepancy")
                    raise LiveBlocked("Unexpected complete fill quantity")
                if status!="FILLED" and filled!=0:
                    ledger.halt("Partial fill in terminal broker order: manual review")
                    raise LiveBlocked("Canceled or rejected order has a partial fill")
                fill=broker_fills(remote,local['quantity']) if status=='FILLED' else None
                ledger.mark_terminal(local, status, fill=fill)
            elif status not in OPEN_STATUSES:
                ledger.halt("Unknown broker order state")
                raise LiveBlocked("Unknown live order state")
    # A recognized but open broker order is normal; wait without resubmission.
    if any(order.get("state") == "ACCEPTED" for order in ledger.data["orders"]):
        return False
    ledger.ready()
    return True


def owned_positions(ledger):
    positions=dict(ledger.data.get("opening_positions") or {})
    for order in ledger.data["orders"]:
        if order["state"]!="FILLED":
            continue
        sym=order["symbol"]
        amount=order["quantity"] * (1 if order["action"]=="BUY" else -1)
        positions[sym] = positions.get(sym,0) + amount
        if positions[sym] < 0:
            raise LiveBlocked("Recorded sell exceeds confirmed buys")
    return {k:v for k,v in positions.items() if v}


def adopt_existing_account_position(ledger, positions):
    """One-time opening inventory for this exact existing $100 Schwab account.

    The user authorized liquidation of exactly two SPYD ETF shares. Never
    automatically adopt another investment or change the baseline after a
    trade, because that could hide an external trade or an accounting error.
    """
    if "opening_positions" in ledger.data:
        return
    if ledger.data["orders"]:
        raise LiveBlocked("Historical bot orders exist without opening position baseline")
    if positions not in ({"SPYD": 2}, {}):
        raise LiveBlocked("Opening inventory is not the expected 2 SPYD ETF shares")
    ledger.data["opening_positions"]=positions.copy()
    ledger.data["opening_inventory_adopted"]=datetime.now(timezone.utc).isoformat()
    ledger.save()
    print("Opening inventory accounted for: two SPYD ETF shares." if positions
          else "Starting brokerage inventory is empty.")


def trading_settlement_pending(ledger, now):
    """Hold all BUY entries until the first market session after a sell."""
    last_sell=None
    for order in ledger.data["orders"]:
        if order.get("action")=="SELL" and order.get("state")=="FILLED":
            created=datetime.fromisoformat(order["created_at"])
            local_day=created.astimezone(ZoneInfo("America/New_York")).date()
            if last_sell is None or local_day>last_sell:
                last_sell=local_day
    if last_sell is None:
        return False
    current_day=now.astimezone(ZoneInfo("America/New_York")).date()
    next_day=last_sell+timedelta(days=1)
    while next_day.weekday()>4:
        next_day+=timedelta(days=1)
    return current_day<next_day


def risk_preflight(ledger, positions, equity, cash, exposure, symbol, settings=None):
    held=owned_positions(ledger)
    if held != positions:
        raise LiveBlocked("Broker positions differ from bot's confirmed fills")
    # Existing positions remain manageable even if the operator lowers the
    # new-entry slot cap. Only the immutable absolute safety limit can halt.
    if len(positions) > MAX_CONCURRENT_POSITIONS:
        raise LiveBlocked("Maximum simultaneously held positions exceeded")
    if exposure > CAPITAL * Decimal("2"):
        raise LiveBlocked("Broker exposure exceeds permitted account isolation")
    now=datetime.now(timezone.utc).date().isoformat()
    if ledger.data["day"] != now:
        ledger.data["day"]=now
        ledger.data["day_start_equity"]=str(equity)
        ledger.save()
    start=money(ledger.data["day_start_equity"], "day start equity")
    hard_limit=DAILY_LOSS if settings is None else min(DAILY_LOSS,Decimal(str(settings['max_daily_loss'])))
    loss_hit = start-equity >= hard_limit
    if loss_hit and not held:
        raise LiveBlocked("Maximum daily account drawdown hit")
    return held.get(symbol,0), loss_hit


def recent_candles(client, symbol):
    bars=result(client.get_price_history_every_five_minutes(
        symbol, need_extended_hours_data=False), "five-minute candles")
    if not isinstance(bars,dict) or not isinstance(bars.get("candles"),list):
        raise LiveBlocked("Price history unavailable")
    return bars["candles"]


def scan_entries(client, now, excluded=()):
    """Rank live market opportunities, excluding symbols already held."""
    quotes=result(client.get_quotes(list(UNIVERSE)), "automated quote batch")
    blocked=set(excluded)
    ranked=[row for row in ranked_candidates(quotes,now)
            if row[1] not in blocked]
    print(f"Market scanner: {len(ranked)} liquid and affordable candidates, "
          f"scanning up to {len(ranked)} trend histories.")
    if not ranked:
        return None
    return choose_entry(ranked,lambda sym:recent_candles(client,sym),now,
                        can_buy=True)


def same_day_filled_buy(ledger, symbol, now):
    """Avoid cash settlement and transitional intraday margin restrictions.

    This conservative policy holds purchases overnight rather than relying on
    broker-specific day-trade permissions that the account API doesn't prove.
    """
    ny_day=now.astimezone(ZoneInfo("America/New_York")).date()
    for order in ledger.data.get("orders",[]):
        if (order.get("symbol")!=symbol or order.get("action")!="BUY"
                or order.get("state")!="FILLED"):
            continue
        try:
            created=datetime.fromisoformat(order["created_at"].replace("Z","+00:00"))
            if created.tzinfo and created.astimezone(
                    ZoneInfo("America/New_York")).date()==ny_day:
                return True
        except (TypeError,ValueError,AttributeError):
            raise LiveBlocked("Cannot establish purchase holding period") from None
    return False


def can_reinvest_confirmed_sale(ledger, now, acct, verified_budget):
    """Permit same-day reinvestment only with affirmative non-borrowed capacity.

    Cash accounts continue to wait for T+1. For a margin-registered account,
    Schwab can make proceeds available the same day without a margin loan,
    but require a cash-backed current balance and explicit broker availability
    field. Existing verified_cash() blocks any margin debt, call, deposits or
    nonzero unsettledCash deduction and caps spending to actual cash.
    """
    if not trading_settlement_pending(ledger,now):
        return True
    sec=acct.get("securitiesAccount") if isinstance(acct,dict) else None
    if not isinstance(sec,dict) or sec.get("type")!="MARGIN":
        return False
    balances=sec.get("currentBalances")
    if not isinstance(balances,dict) or verified_budget<=0:
        return False
    if money(balances.get("marginBalance"),"margin balance")!=0:
        raise LiveBlocked("Reinvestment would involve a margin debt")
    if balances.get("isInCall") is True:
        raise LiveBlocked("Margin call prevents cash-only reinvestment")
    explicit=("cashAvailableForTrading","availableFundsNonMarginableTrade")
    if not any(balances.get(key) is not None and
               money(balances[key],key)>=verified_budget for key in explicit):
        return False
    return True


def _orders_today(ledger, now, action=None):
    day=now.astimezone(ZoneInfo("America/New_York")).date()
    count=0
    for order in ledger.data.get("orders",[]):
        if action is not None and order.get("action")!=action:
            continue
        try:
            created=datetime.fromisoformat(order["created_at"].replace("Z","+00:00"))
            if not created.tzinfo:
                raise ValueError("Missing timezone")
            if created.astimezone(ZoneInfo("America/New_York")).date()==day:
                count+=1
        except (KeyError,TypeError,ValueError,AttributeError):
            raise LiveBlocked("Cannot determine past order trading day") from None
    return count


def _live_risk():
    try:
        return read_live_risk(STATE_DIR)['settings']
    except (OSError,TypeError,KeyError,ValueError) as exc:
        raise LiveBlocked("Cannot validate current live risk settings: "+str(exc)) from None


def _audit(now, symbol, decision, summary, candle=None, signals=None, details=None):
    details=details if isinstance(details,dict) else {}
    log_decision(STATE_DIR,{
        "at":now.isoformat(),"symbol":symbol,"decision":decision,
        "summary":str(summary)[:500],"candle":candle,
        "signals":signals or {},
        "model":str(details.get("model","No model used"))[:96],
        "sentiment":details.get("sentiment"),
        "impact":details.get("impact"),
        "catalyst":str(details.get("catalyst",""))[:180],
        "downside_risk":str(details.get("downside_risk",""))[:180],
        "headlines":(details.get("headlines") or [])[:6]
    })


def attempt(client, account_hash, ledger, now, submit):
    limits=_live_risk()
    # The broker and order journal must independently agree before every order.
    acct,positions,exposure,cash,equity=get_snapshot(client,account_hash)
    adopt_existing_account_position(ledger,positions)
    if not reconcile(client,account_hash,ledger):
        print("Existing Schwab order is pending; no duplicate submission.")
        return
    acct,positions,exposure,cash,equity=get_snapshot(client,account_hash)
    _,loss_hit=risk_preflight(ledger,positions,equity,cash,exposure,
                             next(iter(positions),""),limits)
    if not market_is_normal(client,now):
        print("Market closed / outside allowed session; no order.")
        return
    if _orders_today(ledger,now)>=min(MAX_DAILY_ACTIONS,limits['max_orders_per_day']):
        print("Daily brokerage order cap reached; monitoring existing positions.")
        return

    # First priority is the explicitly authorized SPYD exit, even if other
    # known holdings are present. Reconciliation prevents duplicate attempts.
    sell=None
    if ledger.data.get("opening_positions")=={"SPYD":2} and "SPYD" in positions:
        if positions["SPYD"]!=2:
            raise LiveBlocked("SPYD opening share count changed unexpectedly")
        if any(o.get("action")=="SELL" and o.get("symbol")=="SPYD"
               for o in ledger.data["orders"]):
            raise LiveBlocked("Opening SPYD sell previously attempted; review order")
        sell=("SPYD",positions["SPYD"],int(now.timestamp()*1000),
              "Authorized one-time liquidation of 2 existing SPYD ETF shares")
    if sell is None:
        for sym,held in sorted(positions.items()):
            if same_day_filled_buy(ledger,sym,now):
                print(f"Holding {sym} until next session to avoid settlement/day-trade issues.")
                continue
            action,candle=cross_signal(recent_candles(client,sym),now)
            if action=="SELL":
                sell=(sym,held,candle,
                      "Automatic exit: completed 3/5-bar downward crossover")
                break

    if sell is not None:
        symbol,qty,candle,reason=sell
        quote=result(client.get_quote(symbol),"held-symbol quote")
        bid,ask=quote_levels(quote.get(symbol),now)
        price=sell_limit(bid)
        reason+=(f"; 2-way quote bid={bid}, ask={ask}; "
                 f"limit={price}, shares={qty}")
        action="SELL"
    else:
        if len(positions)>=min(MAX_CONCURRENT_POSITIONS,limits['max_open_positions']):
            print("Maximum concurrent positions held; managing existing inventory.")
            return
        if trading_settlement_pending(ledger,now) and not (
                can_reinvest_confirmed_sale(ledger,now,acct,cash)):
            print("No new buy: sale proceeds have not been verified as "
                  "available for non-borrowed trading.")
            return
        buys_today=_orders_today(ledger,now,action="BUY")
        if loss_hit or buys_today>=min(MAX_DAILY_BUYS,limits['max_buys_per_day']) or cash<Decimal("5"):
            print("No new entries: drawdown, daily-entry cap or insufficient cash.")
            return
        candidate=scan_entries(client,now,excluded=positions.keys())
        if candidate is None:
            if submit:_audit(now,"-","NO_SIGNAL","No eligible completed 3/5-bar upward crossover; stay in cash",
                              signals={"candidate_universe":len(UNIVERSE)})
            print("No qualifying automatic entry signal; remain in available cash.")
            return
        allowed,ai_reason=approve_entry(candidate.symbol,now)
        details=research_evidence(candidate.symbol,now)
        signals={"technical":candidate.reason,"rank":str(candidate.score),
                 "bid":str(candidate.bid),"ask":str(candidate.ask),
                 "rule":"completed 3/5-bar crossover"}
        if not allowed:
            if submit:_audit(now,candidate.symbol,"AI_VETO",ai_reason,
                              candidate.candle,signals,details)
            print(f"AI gated entry for {candidate.symbol}: {ai_reason}")
            return
        symbol=candidate.symbol
        candle=candidate.candle
        discretionary=min(cash*Decimal(str(limits['allocation_pct']))/100,
                         Decimal(str(limits['max_order_usd'])),
                         CAPITAL*Decimal(str(limits['max_position_pct']))/100)
        qty,price=buy_quantity(candidate.ask,discretionary,exposure)
        action="BUY"
        reason=(candidate.reason+f"; {ai_reason}; selected quantity={qty}; "
                f"budgeted limit={price}; verified cash={cash}")
    if candle<=ledger.data.get("last_candle",0):
        print("Signal already processed on this candle; skip.")
        return
    if not qty or price<=0 or (action=="BUY" and price*qty>CAPITAL):
        print("Strategy signal exists but cash/capital prevents order.")
        return
    print(f"AUTONOMOUS DECISION: {action} {qty} {symbol} @ {price}; {reason}")
    if not submit:
        print("Order preview only: execution has not been activated.")
        return
    # Record the observable decision and supporting facts before broker POST.
    # Rule-based opening SPYD sells do NOT pretend to involve AI inference.
    if action=="SELL":
        _audit(now,symbol,"ORDER_INTENT",reason,candle,
               {"rule":"Authorized SPYD liquidation" if symbol=="SPYD" else "3/5-bar downward crossover",
                "bid":str(bid),"ask":str(ask),"limit":str(price)},
               {"model":"No AI used for sell decision"})
    else:
        _audit(now,symbol,"ORDER_INTENT",reason,candle,signals,details)
    from schwab.orders.equities import equity_buy_limit,equity_sell_limit
    from schwab.utils import Utils
    entry=ledger.record_before_network(symbol,action,qty,price,candle,
                                       reason=reason)
    try:
        order=(equity_buy_limit(symbol,qty,float(price)) if action=="BUY"
               else equity_sell_limit(symbol,qty,float(price))).build()
        response=client.place_order(account_hash,order)
        if response.status_code not in (200,201):
            ledger.halt("Schwab order response was not success")
            raise LiveBlocked("Broker order not confirmed; halted")
        order_id=Utils(client,account_hash).extract_order_id(response)
        if order_id is None:
            ledger.halt("No confirmed broker order ID")
            raise LiveBlocked("Order ID missing: halted to prevent retry")
        ledger.mark_accepted(entry,order_id)
        print(f"Schwab accepted autonomous {action} DAY LIMIT; order ID journaled.")
    except BaseException:
        ledger.halt("Order POST outcome requires broker verification")
        raise

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check",action="store_true",help="Read-only account check")
    parser.add_argument("--once",action="store_true",help="One scan (can submit if armed)")
    parser.add_argument("--run",action="store_true",help="Continuous live worker")
    args=parser.parse_args()
    if sum((args.check,args.once,args.run))!=1:
        parser.error("Choose exactly one mode")
    account_hash=os.getenv("LIVE_ACCOUNT_HASH","").strip()
    mode=os.getenv("LIVE_MODE","").strip()
    activated=os.getenv("LIVE_TRADING","false").lower()=="true"
    if mode!="AUTONOMOUS":
        raise LiveBlocked("Autonomous trading mode must be explicitly configured")
    if args.run and not activated:
        raise LiveBlocked("LIVE_TRADING=true required for continuous operation")
    STATE_DIR.mkdir(mode=0o700,parents=True,exist_ok=True)
    with (STATE_DIR/"worker.lock").open("a+") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        client=broker()
        confirm_account(client,account_hash)
        print("Schwab brokerage authorized; cash-only autonomous execution mode.")
        if args.check:
            _,pos,exposure,cash,equity=get_snapshot(client,account_hash)
            ledger=OrderLedger.open(JOURNAL)
            adopt_existing_account_position(ledger,pos)
            if not reconcile(client,account_hash,ledger):
                raise LiveBlocked("Outstanding order prevents launch")
            if len(pos)>MAX_CONCURRENT_POSITIONS:
                raise LiveBlocked("More than permitted held positions")
            risk_preflight(ledger,pos,equity,cash,exposure,next(iter(pos),""))
            # The batch API proves the automated candidate universe is accessible;
            # a closed market may not provide fresh buyable quotes.
            market_quotes=result(client.get_quotes(list(UNIVERSE)),
                                 "automated market quote screening")
            if not isinstance(market_quotes,dict) or not any(
                isinstance(market_quotes.get(s),dict) for s in UNIVERSE):
                raise LiveBlocked("Schwab did not return eligible market instruments")
            print(f"Autonomous market data feed verified; "
                  f"{len(market_quotes)} quote records returned.")
            print(f"Broker read only: positions={len(pos)}, exposure={exposure}, "
                  f"conservative cash={cash}, account equity={equity}.")
            print("No order submission in --check mode.")
            return
        ledger=OrderLedger.open(JOURNAL)
        while True:
            try:
                mode=operator_mode()
                write_heartbeat(activated,mode)
                if mode=="running":
                    attempt(client,account_hash,ledger,datetime.now(timezone.utc),
                            submit=activated)
                else:
                    print("Trading permission paused in authenticated dashboard; no new orders.")
            except LiveBlocked as exc:
                print(f"BLOCKED: {exc}",file=sys.stderr)
                if args.run:
                    # Never spin while an unresolved order or bad broker state persists.
                    raise
                return 2
            if not args.run:
                return
            # Refresh heartbeat every 10 seconds, scan at most every 5 minutes.
            # Detect a dashboard resume promptly without polling the broker.
            for _ in range(30):
                time.sleep(10)
                next_mode=operator_mode()
                write_heartbeat(activated,next_mode)
                if next_mode!=mode:
                    break


if __name__=="__main__":
    try:
        sys.exit(main())
    except (LiveBlocked, PermissionError, FileNotFoundError, BlockingIOError) as exc:
        print(f"SAFE STOP: {exc}",file=sys.stderr)
        sys.exit(2)
