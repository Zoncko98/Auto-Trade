"""Continuous Webull stock/crypto scans with isolated AI, risk and order lifecycle.

The only live submission path requires an explicit Webull policy, selected
authenticated cash account, separate saved risk plan, fresh broker quotes,
broker orders check and a pre-written unique journal intent. Never borrows
Robinhood positions, pending orders or live execution permission.
"""
import json,os,time,re
from datetime import datetime,timezone
from decimal import Decimal,ROUND_DOWN
from pathlib import Path
from uuid import uuid4
from webull_broker import WebullBroker,WebullError,positive
from webull_trade_config import read as read_policy,WebullPolicyError
from webull_trade_config import LIVE_EXECUTION_VERIFIED
from webull_risk import read as read_risk
from webull_account_preferences import read as read_account_preferences
from webull_journal import WebullJournal,JournalBlocked
from webull_signals import evaluate,_quote,core_stock_session,WebullSignalError
from dashboard_control import write_atomic
from webull_streaming import read_snapshot, market_observation, feed_status
from webull_stock_strategy import (STOCK_SCAN_SYMBOLS, STOCK_SOURCE,
                                   STOCK_DISCOVERY_UNIVERSE, STOCKS_PER_CYCLE, rotating_stock_batch,
                                   scan_webull_stock, revalidate_webull_stock)

STOCKS=STOCK_SCAN_SYMBOLS  # Same equity universe as Schwab.
CRYPTOS=("BTCUSD","ETHUSD","SOLUSD","DOGEUSD","XRPUSD","AVAXUSD")
MAX_STOCKS_PER_CYCLE=STOCKS_PER_CYCLE  # Bounded quotes; rotate across expanded universe.
MAX_SCAN_PER_CLASS=3  # Crypto retains its existing one-minute strategy.

class WebullBlocked(RuntimeError):pass

def market_readiness(signals):
    """Summarize actual broker market-data gate results, not execution readiness."""
    result={}
    for asset,label in (("EQUITY","stocks"),("CRYPTO","crypto")):
        rows=[r for r in signals if r.get("asset")==asset]
        eligible=sum(r.get("technical_approved") is True for r in rows)
        permission=sum(r.get("reason")=="MARKET_DATA_WEBULL_HTTP_403" for r in rows)
        spread=sum("SPREAD_ABOVE_0_5" in str(r.get("reason","")) for r in rows)
        if not rows:
            state,detail="NOT_SCANNED","No market observations recorded"
        elif permission==len(rows):
            state,detail="MARKET_DATA_PERMISSION_REQUIRED",(
                "Webull stock quote API returns HTTP 403; check app-key entitlements, "
                "individual endpoint status and request authentication before concluding subscription is missing")
        elif spread==len(rows):
            state,detail="BROKER_SPREAD_TOO_WIDE",(
                "Webull bid/ask spread exceeds the existing 0.5% strategy limit; "
                "no buy signal permitted")
        elif eligible:
            state,detail="CANDIDATE_FOUND",(
                "Technical candidate found; AI approval and broker risk checks remain separate")
        elif any(r.get("reason","").startswith("MARKET_DATA_") for r in rows):
            state,detail="MARKET_DATA_DEGRADED",(
                "One or more broker market-data checks failed")
        else:
            state,detail="SCANNING_NO_SIGNAL",(
                "Quotes checked; no qualifying shared Schwab M5 stock entry"
                if asset=="EQUITY" else
                "Quotes checked; no approved crypto momentum entry")
        result[label]={"status":state,"detail":detail,"checked":len(rows),
                       "candidates":eligible,"permission_errors":permission,
                       "spread_blocks":spread}
    return result

def _now():return datetime.now(timezone.utc)

def _safe_public(exc):
    # SDK exceptions may contain signed headers. Only expose status codes
    # or our own local, static signal validation messages.
    if isinstance(exc,WebullSignalError):
        return "SIGNAL_"+re.sub(r"[^A-Z0-9]+","_",str(exc).upper()).strip("_")[:90]
    if isinstance(exc,WebullError) or type(exc).__name__=="ServerException":
        status=re.search(r"HTTP (?:Status: )?([45]\d\d)",str(exc))
        if status:return "WEBULL_HTTP_"+status.group(1)
    if isinstance(exc,WebullError):
        static={
            "Broker quote ambiguous":"WEBULL_QUOTE_AMBIGUOUS",
            "Broker quote unavailable":"WEBULL_QUOTE_FORMAT_UNEXPECTED",
            "Missing symbol-specific market bars":"WEBULL_BARS_FORMAT_UNEXPECTED",
            "No executable broker bid/ask":"WEBULL_BID_ASK_UNAVAILABLE",
            "Unexpected broker list response":"WEBULL_LIST_FORMAT_UNEXPECTED"}
        if str(exc) in static:return static[str(exc)]
    return type(exc).__name__

def _account_class(row):
    return str(row.get("account_class") or row.get("account_type") or "").upper()

def _can_trade_account(account,asset,allow_margin_accounts=False):
    role=_account_class(account)
    if "MARGIN" in role:
        # Opt-in is only for the known US individual margin classification.
        # It allows cash-funded equity trades, never borrowing or crypto here.
        return bool(allow_margin_accounts) and role=="INDIVIDUAL_MARGIN" and asset=="EQUITY"
    if asset=="CRYPTO":return "CRYPTO" in role
    # Hide and exclude cash-classified stock accounts from Webull autonomous
    # account selection as requested; never delete accounts at the broker.
    if "CASH" in role:return False
    return any(x in role for x in ("STOCK","EQUITY")) and "CRYPTO" not in role

def account_readiness(account,allow_margin_accounts=False):
    """Account verification never implies order eligibility or live authorization."""
    label=_account_class(account)
    margin="MARGIN" in label
    stock=_can_trade_account(account,"EQUITY",allow_margin_accounts)
    crypto=_can_trade_account(account,"CRYPTO",allow_margin_accounts)
    return {"account_id":account["account_id"],"account_type":label,
            "stocks_cash_eligible":stock,"crypto_cash_eligible":crypto,
            "margin_cash_only_opt_in":bool(allow_margin_accounts),
            "margin_borrowing_enabled":False,
            "status":("CASH_ACCOUNT_EXCLUDED_FROM_TRADING" if "CASH" in label and "CRYPTO" not in label else
                      "MARGIN_CASH_ONLY_ELIGIBLE" if margin and stock else
                      "MARGIN_ACCOUNT_BLOCKED" if margin else
                      "ACCOUNT_CLASS_ELIGIBLE" if (stock or crypto) else
                      "ACCOUNT_CLASS_UNVERIFIED"),
            "reason":("Cash-classified account excluded from Webull trading controls by operator request; broker connection preserved"
                      if "CASH" in label and "CRYPTO" not in label else
                      "Margin-classified Webull stock account opted into CASH-ONLY eligibility; "
                      "broker-reported positive cash, no reported margin debt or calls, market data, risk and execution checks required; absence of optional margin/settlement fields is not proof of zero borrowing"
                      if margin and stock else
                      "Margin account opt-in is off or account type unsupported; no orders"
                      if margin else
                      "Account class is eligible; market data, funds, order status, risk and AI still require checks"
                      if stock or crypto else
                      "No verified cash-stock or spot-crypto account class; live orders blocked")}

def verify_margin_cash_funding(balance):
    """Cash-only budget for a margin-classified brokerage account.

    Webull documents that margin accounts may omit settled_cash, buying_power,
    and used_margin. Do not interpret absent used_margin as zero; instead cap
    any new BUY by independently returned *cash balances*, never day BP.
    Positive reported utilization, debit or margin calls always reject.
    """
    if not isinstance(balance,dict) or balance.get("total_asset_currency")!="USD":
        raise WebullBlocked("Broker USD cash balance unavailable")
    if balance.get("open_margin_calls") not in (None,"","[]",[]):
        raise WebullBlocked("Margin call restriction")
    for key in ("used_margin","used_margin_for_open_order","margin_debit"):
        if balance.get(key) not in (None,""):
            if positive(balance[key],allow_zero=True)!=0:
                raise WebullBlocked("Reported margin usage or debit blocks cash-only trading")
    assets=balance.get("account_currency_assets")
    usd=[a for a in assets if isinstance(a,dict) and a.get("currency")=="USD"] if isinstance(assets,list) else []
    if len(usd)!=1:
        raise WebullBlocked("Unique broker USD cash record required")
    cash=positive(usd[0].get("cash_balance"),allow_zero=True)
    total=positive(balance.get("total_cash_balance"),allow_zero=True)
    available=min(cash,total)
    # If supplied, further reduce usable cash; never substitute margin buying power.
    for key in ("settled_cash","buying_power"):
        if usd[0].get(key) not in (None,""):
            available=min(available,positive(usd[0][key],allow_zero=True))
    for key in ("held_amount","frozen_amount"):
        if usd[0].get(key) not in (None,""):
            available=max(Decimal("0"),available-positive(usd[0][key],allow_zero=True))
    return available

def _funds(balance):
    if not isinstance(balance,dict) or balance.get("total_asset_currency")!="USD":
        raise WebullBlocked("USD account valuation not verified")
    equity=positive(balance.get("total_net_liquidation_value"))
    if balance.get("open_margin_calls") not in (None,"","[]",[]):
        raise WebullBlocked("Margin call restriction")
    used=positive(balance.get("used_margin","0"),allow_zero=True)
    if used!=0:raise WebullBlocked("Margin usage detected")
    entries=balance.get("account_currency_assets")
    usd=[x for x in entries if isinstance(x,dict) and x.get("currency")=="USD"] if isinstance(entries,list) else []
    if len(usd)!=1:raise WebullBlocked("Unique USD cash balance missing")
    a=usd[0]
    available=min(positive(a.get("cash_balance"),allow_zero=True),
                  positive(balance.get("total_cash_balance"),allow_zero=True))
    # Webull omits buying_power and settled_cash for margin-class accounts.
    # Never use day_buying_power, overnight_buying_power, or option_buying_power
    # as substitutes for actual cash.
    for key in ("buying_power","settled_cash"):
        if a.get(key) not in (None,""):
            available=min(available,positive(a[key],allow_zero=True))
    day=balance.get("total_day_profit_loss")
    if day is None:raise WebullBlocked("Broker day P/L not verified")
    try:
        pnl=Decimal(str(day))
        if not pnl.is_finite():raise ValueError
    except (TypeError,ValueError):
        raise WebullBlocked("Broker day P/L invalid") from None
    return equity,available,pnl

def _live_gate(root,broker,policy,risk,account_id,asset,symbol,side,qty,price,journal):
    if policy["enabled"] is not True:raise WebullBlocked("Webull live trading not armed")
    if getattr(broker,"environment",None)!="production":
        raise WebullBlocked("Real-money Webull execution requires production API environment")
    if risk.get("saved") is not True:raise WebullBlocked("Save Webull risk limits before live trading")
    kind="trade_stocks" if asset=="EQUITY" else "trade_crypto"
    selected="stock_account" if asset=="EQUITY" else "crypto_account"
    if not policy[kind] or policy[selected]!=account_id:
        raise WebullBlocked("Asset class/account not explicitly enabled")
    account=broker.verify_account(account_id)
    allow_margin=read_account_preferences(root)["allow_margin_accounts"]
    if not _can_trade_account(account,asset,allow_margin):
        raise WebullBlocked("Selected account class not permitted by Webull cash-only profile")
    if asset=="EQUITY" and not core_stock_session(_now()):
        raise WebullBlocked("US core trading session not open")
    if journal.pending(account_id):raise WebullBlocked("Unresolved Webull order intent")
    orders=broker.open_orders(account_id)
    if orders:raise WebullBlocked("Existing open broker orders block autonomous execution")
    balance=broker.balance(account_id)
    margin_cash_budget=None
    if "MARGIN" in _account_class(account):
        margin_cash_budget=verify_margin_cash_funding(balance)
    equity,cash,pnl=_funds(balance)
    if margin_cash_budget is not None:cash=min(cash,margin_cash_budget)
    if pnl<=-Decimal(str(risk["max_daily_loss_usd"])):
        raise WebullBlocked("Maximum broker-reported daily loss reached")
    bot_positions,_=journal.positions(account_id)
    # Market exposure includes any externally held positions, not just bot inventory.
    holdings=broker.positions(account_id)
    if not isinstance(holdings,list):raise WebullBlocked("Broker holdings unavailable")
    broker_positions={}
    for row in holdings:
        if not isinstance(row,dict):raise WebullBlocked("Broker position invalid")
        key=(row.get("symbol"),row.get("instrument_type"))
        if key in broker_positions:raise WebullBlocked("Ambiguous broker position")
        broker_positions[key]=positive(row.get("quantity"),allow_zero=True)
    limit=Decimal(str(risk["max_order_usd"]))
    exposure_pct=Decimal(str(risk["max_position_pct"]))
    if limit<=0 or limit>1000 or exposure_pct<=0 or exposure_pct>10:
        raise WebullBlocked("Live risk hard caps exceeded")
    if not (0<risk["max_daily_loss_usd"]<=250 and 1<=risk["max_open_positions"]<=10):
        raise WebullBlocked("Live risk policy outside hard caps")
    price=positive(price);qty=positive(qty)
    if side=="BUY":
        if (symbol,asset) in broker_positions and broker_positions[(symbol,asset)]>0:
            raise WebullBlocked("Existing broker holding; no averaging up")
        if len([r for r in broker_positions.values() if r>0])>=risk["max_open_positions"]:
            raise WebullBlocked("Maximum open broker positions reached")
        notional=qty*price
        budget=min(limit,cash*Decimal("0.25"),equity*exposure_pct/100)
        if notional>budget:raise WebullBlocked("Order exceeds account-specific risk budget")
        account_holdings_value=positive(balance.get("total_market_value"),allow_zero=True)
        if account_holdings_value+notional>equity*Decimal("0.25"):
            raise WebullBlocked("Account market exposure would exceed 25% of equity")
        if asset=="CRYPTO" and notional<Decimal("2"):
            raise WebullBlocked("Crypto below Webull minimum order")
    else:
        row=bot_positions.get(symbol)
        if row is None or row.get("asset")!=asset:
            raise WebullBlocked("Not a bot-acquired position")
        if qty>positive(row["quantity"]):
            raise WebullBlocked("Sell exceeds verified bot-owned amount")
        broker_held=broker_positions.get((symbol,asset))
        if broker_held is None or qty>broker_held:
            raise WebullBlocked("Broker holdings do not cover bot sale")
        if asset=="CRYPTO":
            remainder=broker_held-qty
            if remainder>0 and remainder*price<Decimal("2"):
                raise WebullBlocked("Crypto sell would leave below-minimum remainder")
    return {"account":account_id,"equity":str(equity),
            "cash":str(cash),"day_pnl":str(pnl),
            "max_order_usd":str(limit),"side":side,"asset":asset}

def _order(root,broker,policy,risk,journal,account,sym,asset,side,signal,qty,price,reason):
    # Fail closed on old decisions and re-fetch a fresh executable broker quote.
    when=datetime.fromisoformat(signal["at"].replace("Z","+00:00"))
    if not 0<=( _now()-when).total_seconds()<=90:
        raise WebullBlocked("Signal expired")
    q=broker.quote(sym,asset)
    bid,ask,spread=_quote(q,_now())
    if side=="BUY":
        if signal.get("technical_approved") is not True or signal.get("ai_approved") is not True:
            raise WebullBlocked("Entry requires validated signal and AI approval")
        # Avoid buying when prices have moved during an expensive AI review.
        if abs(ask/positive(signal["ask"])-1)*100>Decimal("0.75"):
            raise WebullBlocked("Entry quote moved during review")
        price=ask
    else:
        price=bid
    _live_gate(root,broker,policy,risk,account,asset,sym,side,qty,price,journal)
    order_id=uuid4().hex
    payload={"combo_type":"NORMAL","client_order_id":order_id,"symbol":sym,
             "instrument_type":asset,"market":"US","order_type":"LIMIT",
             "limit_price":str(price),"quantity":str(qty),"side":side,
             "time_in_force":"DAY","entrust_type":"QTY"}
    if asset=="EQUITY":payload["support_trading_session"]="CORE"
    if asset=="EQUITY":
        # Webull's preview endpoint is non-executing and supports stock orders;
        # it is explicitly NOT supported for crypto. A rejected stock preview
        # cannot create an intent or result in a broker order.
        result=broker.preview(account,payload)
        if (not isinstance(result,dict) or result.get("success") is False or
                result.get("errors") or result.get("error")):
            raise WebullBlocked("Stock order preview was not accepted")
    journal.new_intent(account,order_id,sym,asset,side,str(qty),str(price),reason)
    # Never auto-retry this call, including timeouts; reconciliation by ID first.
    receipt=broker.place(account,payload)
    journal.acknowledged(order_id,receipt)
    return {"client_order_id":order_id,"state":"BROKER_ACKNOWLEDGED_UNFILLED",
            "symbol":sym,"asset":asset,"side":side}

def _peak(root,account,symbol,bid,opened_at):
    path=Path(root)/"webull"/"peaks.json"
    try:data=json.loads(path.read_text())
    except FileNotFoundError:data={}
    if not isinstance(data,dict):raise WebullBlocked("Peak record corrupt")
    key=account+"/"+symbol
    stored=data.get(key)
    # Never use a peak from a previous, already-closed position.
    previous=(positive(stored["bid"],allow_zero=True)
              if isinstance(stored,dict) and stored.get("opened_at")==opened_at
              else Decimal("0"))
    value=max(previous,bid)
    data[key]={"opened_at":opened_at,"bid":str(value)}
    write_atomic(path,data)
    return value

def _exit_reason(root,account,symbol,row,signal,risk):
    if row.get("opened_at") is None:raise WebullBlocked("Position fill timestamp unavailable")
    bid=positive(signal["bid"]);cost=positive(row["cost_basis"])
    hold=( _now()-datetime.fromisoformat(row["opened_at"].replace("Z","+00:00")) ).total_seconds()/60
    pnl=(bid*Decimal("0.9975")/cost-1)*100
    peak=_peak(root,account,symbol,bid,row["opened_at"])
    peak_net=(peak*Decimal("0.9975")/cost-1)*100
    retreat=(1-bid/peak)*100
    if pnl<=Decimal("-2"):return "STOP_LOSS"
    if hold>=15 and pnl>=Decimal("3"):return "TAKE_PROFIT"
    if hold>=15 and peak_net>=Decimal("2") and retreat>=Decimal("0.75") and pnl>=Decimal("1"):
        return "TRAILING_PROTECTION"
    if hold>=15 and signal.get("technical_exit") and pnl>=Decimal("1"):
        return "TECHNICAL_PROFIT_REVERSAL"
    return None

def _scan(root,broker,rotation,report):
    from ai_research import approve_entry,research_evidence
    # Discover-only / monitor scans continue whether live execution is armed.
    stocks=list(rotating_stock_batch(rotation))  # Rotate; retain Webull M5 rules and API budget.
    cryptos=[CRYPTOS[(rotation+i)%len(CRYPTOS)]
             for i in range(MAX_SCAN_PER_CLASS)]
    report["scan_universe"]={"stocks":len(STOCK_DISCOVERY_UNIVERSE),"crypto":len(CRYPTOS),
                             "stocks_per_cycle":len(stocks),"stock_batch_offset":rotation%len(STOCK_DISCOVERY_UNIVERSE)}
    report["scanned_symbols"]=stocks+cryptos
    report["signals"]=[]
    report["stock_strategy"]="WEBULL_INDEPENDENT_SCHWAB_MIRROR_M5"
    stream=read_snapshot(root)
    report["stream_feeds"]=feed_status(root)
    observed=[]
    # Independent Webull stock engine MIRRORS (but never imports) the Schwab
    # 3/5-bar crossover, candidate ranking, and continuation thresholds.
    try:
        stock_rows,stock_candidate=scan_webull_stock(broker,stocks,_now())
        report["signals"].extend(stock_rows)
        if stock_candidate:observed.append(stock_candidate)
    except Exception as exc:
        report["signals"].extend({"symbol":symbol,"asset":"EQUITY",
             "source":STOCK_SOURCE,"technical_approved":False,
             "reason":"MARKET_DATA_"+_safe_public(exc)} for symbol in stocks)
    # Existing Webull crypto strategy is unchanged. Coinbase is still
    # discovery-only; Webull independently verifies quotes before an order.
    for symbol in cryptos:
        asset="CRYPTO"
        origin="WEBULL_M1"
        try:
            external=market_observation(stream,asset,symbol)
            if external:
                origin=external["source"]
                result=evaluate(symbol,asset,external["quote"],
                    external["bars"],source=origin)
            else:
                q=broker.quote(symbol,asset)
                time.sleep(1.05)
                bars=broker.bars(symbol,asset)
                time.sleep(1.05)
                result=evaluate(symbol,asset,q,bars)
            report["signals"].append({k:result.get(k) for k in
                ("symbol","asset","technical_approved","momentum_pct","spread_pct","reason","source")})
            if result.get("technical_approved"):observed.append(result)
        except Exception as exc:
            report["signals"].append({"symbol":symbol,"asset":asset,"source":origin,
                "technical_approved":False,"reason":"MARKET_DATA_"+_safe_public(exc)})
    observed.sort(key=lambda v:(v.get("momentum_pct") or 0),reverse=True)
    report["ai_reviews"]=[]
    approved=[]
    for row in observed[:2]:
        name=row["symbol"][:-3]+"-USD" if row["asset"]=="CRYPTO" else row["symbol"]
        started=time.monotonic()
        try:
            # Use the currently deployed common AI news reviewer. A future
            # technical-only crypto reviewer must be deployed and separately
            # validated before changing this gate on a live account.
            accepted,reason=approve_entry(name,_now())
            evidence=research_evidence(name,_now())
            model=evidence.get("model")
        except Exception as exc:
            accepted=False;reason="AI_UNAVAILABLE_"+_safe_public(exc);model=None
        report["ai_reviews"].append({
            "symbol":row["symbol"],"asset":row["asset"],"approved":accepted,
            "model":model,"duration_seconds":round(time.monotonic()-started,2),
            "reason":str(reason)[:230]})
        if accepted:approved.append(dict(row,ai_approved=True))
    report["candidates"]=len(observed)
    return approved

def run_cycle(root,broker,rotation=0):
    root=Path(root)
    journal=WebullJournal(root)
    policy=read_policy(root)
    risk=read_risk(root)
    report={"updated_at":_now().isoformat(),"worker":"RUNNING",
        "execution_status":"DISARMED" if not policy["enabled"] else "ARMED_NO_ORDER",
        "live_orders_allowed":policy["enabled"] is True and getattr(broker,"environment",None)=="production",
        "execution_verified":LIVE_EXECUTION_VERIFIED,
        "operator_authorized_unvalidated":policy["enabled"] is True and not LIVE_EXECUTION_VERIFIED,
        "environment":getattr(broker,"environment","unknown"),
        "policy":policy,"risk_saved":risk.get("saved",False),
        "broker_accounts":[],"account_summaries":[],
        "reconciliation":[],"orders":[]}
    accounts=broker.accounts()
    report["broker_accounts"]=[{"account_id":a["account_id"],
           "account_type":_account_class(a)} for a in accounts]
    allow_margin=read_account_preferences(root)["allow_margin_accounts"]
    report["account_readiness"]=[account_readiness(a,allow_margin) for a in accounts]
    # Stock OpenAPI entitlement probe checks three read-only endpoints.
    # A portal authorization alone cannot identify which SDK call receives 403.
    probe_path=root/"webull"/"stock_api_probe.json"
    if rotation%len(STOCKS)==0 and hasattr(broker,"stock_api_probe"):
        try:
            result=broker.stock_api_probe()
            result["checked_at"]=_now().isoformat()
            write_atomic(probe_path,result)
        except Exception:
            # Never interfere with account reconciliation or order safeguards.
            pass
    try:
        report["stock_api_probe"]=json.loads(probe_path.read_text())
    except (OSError,ValueError,TypeError):
        report["stock_api_probe"]={"state":"PENDING_FIRST_CHECK"}
    account_ids={a["account_id"] for a in accounts}
    # Reconcile all journal accounts, including disabled ones and after restarts.
    found={r["account"] for r in journal.recent(100)}
    for account in sorted(found & account_ids):
        report["reconciliation"].extend(journal.reconcile(account,broker))
    # Read balances for accounts selected for trading. Querying every linked
    # broker account each cycle previously hit the 2-per-2-second API quota,
    # hiding the actual reason that eligible orders were not reached.
    active_ids={policy["stock_account"] if policy["trade_stocks"] else "",
                policy["crypto_account"] if policy["trade_crypto"] else ""}
    for account in accounts:
        if account["account_id"] not in active_ids:
            continue
        try:
            b=broker.balance(account["account_id"])
            report["account_summaries"].append({
               "account_id":account["account_id"],"environment":report["environment"],
               "currency":b.get("total_asset_currency"),
               "account_value":b.get("total_net_liquidation_value"),
               "cash":b.get("total_cash_balance"),
               "day_pnl":b.get("total_day_profit_loss")})
        except Exception as exc:
            report["account_summaries"].append({"account_id":account["account_id"],
               "status":"BALANCE_UNAVAILABLE","reason":_safe_public(exc)})
    # A selected account with an unavailable balance is not ready to execute,
    # even if a policy flag is armed. Report this before scanning candidates.
    if policy["enabled"]:
        for status in report["account_summaries"]:
            if status.get("status")=="BALANCE_UNAVAILABLE":
                report["execution_status"]="ARMED_ACCOUNT_DATA_UNAVAILABLE"
                report["execution_reason"]=(
                    "BROKER_RATE_LIMITED_HTTP_429" if status.get("reason")=="WEBULL_HTTP_429"
                    else "SELECTED_ACCOUNT_BALANCE_UNAVAILABLE")
                break
    all_positions={}
    for account in sorted(found | {policy["stock_account"],policy["crypto_account"]}):
        if not account or account not in account_ids:continue
        try:
            owned,pnl=journal.positions(account)
            all_positions[account]={"holdings":owned,"realized_pnl_usd":pnl}
        except Exception as exc:
            all_positions[account]={"status":"JOURNAL_UNAVAILABLE","reason":_safe_public(exc)}
    report["bot_portfolios"]=all_positions
    report["pending_orders"]=[r for r in journal.recent(40) if r["status"] not in ("FILLED","CANCELLED","FAILED")]
    report["orders"]=journal.recent(20)
    # Never submit new orders while any Webull journal entry is unresolved.
    if policy["enabled"] and report["pending_orders"]:
        report["execution_status"]="RECONCILIATION_PENDING"
    approvals=_scan(root,broker,rotation,report)
    report["market_readiness"]=market_readiness(report.get("signals",[]))
    report["approved_candidates"]=[{"symbol":x["symbol"],"asset":x["asset"]} for x in approvals]
    # Independently managed Webull-owned exit protection. No Robinhood inventory.
    if policy["enabled"] and not report["pending_orders"]:
        for account in (policy["stock_account"],policy["crypto_account"]):
            if not account or account not in account_ids:continue
            try:owned,_=journal.positions(account)
            except Exception:continue
            for symbol,row in owned.items():
                asset=row["asset"]
                if asset=="EQUITY" and not core_stock_session(_now()):continue
                try:
                    quote=broker.quote(symbol,asset)
                    bid,ask,spread=_quote(quote,_now())
                    signal={"symbol":symbol,"asset":asset,"at":_now().isoformat(),
                            "bid":str(bid),"ask":str(ask),"technical_exit":False}
                    try:
                        technical=evaluate(symbol,asset,quote,broker.bars(symbol,asset))
                        signal["technical_exit"]=technical.get("technical_exit") is True
                    except (WebullSignalError,WebullError,ValueError,TypeError):
                        pass  # Stop-loss and take-profit still use fresh broker bid.
                    exit_reason=_exit_reason(root,account,symbol,row,signal,risk)
                    if not exit_reason:continue
                    _order(root,broker,policy,risk,journal,account,symbol,asset,"SELL",
                        signal,row["quantity"],signal["bid"],exit_reason)
                    report["execution_status"]="EXIT_SUBMITTED_UNCONFIRMED"
                    break
                except Exception as exc:
                    report["execution_status"]="EXIT_BLOCKED"
                    report["execution_reason"]=_safe_public(exc)
            if report["execution_status"]=="EXIT_SUBMITTED_UNCONFIRMED":break
    if policy["enabled"] and report["execution_status"]=="ARMED_NO_ORDER":
        for sig in approvals:
            try:
                elapsed=(_now()-datetime.fromisoformat(sig["at"].replace("Z","+00:00"))).total_seconds()
                if elapsed>60:
                    if sig["asset"]=="EQUITY" and sig.get("source")==STOCK_SOURCE:
                        fresh=revalidate_webull_stock(broker,sig["symbol"],_now())
                    else:
                        fresh=evaluate(sig["symbol"],sig["asset"],
                                       broker.quote(sig["symbol"],sig["asset"]),
                                       broker.bars(sig["symbol"],sig["asset"]))
                    if fresh.get("technical_approved") is not True:
                        raise WebullBlocked("Signal no longer qualifies after AI review")
                    previous=positive(sig["mid"]);current=positive(fresh["mid"])
                    if abs(current/previous-1)*100>Decimal("0.75"):
                        raise WebullBlocked("Signal drifted after AI review")
                    sig=dict(fresh,ai_approved=True,revalidated_after_ai=True)
            except Exception as exc:
                report["execution_status"]="ENTRY_REVALIDATION_BLOCKED"
                report["execution_reason"]=_safe_public(exc)
                continue
            account=policy["stock_account"] if sig["asset"]=="EQUITY" else policy["crypto_account"]
            try:
                if not account:raise WebullBlocked("No selected account")
                b=broker.balance(account)
                equity,cash,pnl=_funds(b)
                budget=min(Decimal(str(risk["max_order_usd"])),cash*Decimal(".25"),
                           equity*Decimal(str(risk["max_position_pct"]))/100)
                ask=positive(sig["ask"])
                step=Decimal("1") if sig["asset"]=="EQUITY" else Decimal("0.00000001")
                qty=(budget/ask/step).to_integral_value(rounding=ROUND_DOWN)*step
                if qty<=0:raise WebullBlocked("Account risk budget too small")
                receipt=_order(root,broker,policy,risk,journal,account,
                       sig["symbol"],sig["asset"],"BUY",sig,qty,ask,
                       ("Webull independent M5 mirror signal + Webull AI review"
                        if sig["asset"]=="EQUITY" else
                        "Webull crypto momentum + AI approval"))
                report["execution_status"]="ENTRY_SUBMITTED_UNCONFIRMED"
                report["last_submission"]=receipt
                break
            except Exception as exc:
                report["execution_status"]="BLOCKED_"+_safe_public(exc)
                report["execution_reason"]=_safe_public(exc)
    report["updated_at"]=_now().isoformat()
    # Dashboard reports unresolved submission evidence, never a fabricated fill.
    return report

def _persist(root,report):
    write_atomic(Path(root)/"webull"/"worker_status.json",report)
    history=Path(root)/"webull"/"decision_history.json"
    try:old=json.loads(history.read_text())
    except (OSError,ValueError):old=[]
    if not isinstance(old,list):old=[]
    entry={k:report.get(k) for k in (
        "updated_at","execution_status","execution_reason","scan_universe",
        "scanned_symbols","stock_strategy","signals","ai_reviews","approved_candidates",
        "reconciliation","pending_orders","last_submission","market_readiness","stream_feeds","stock_api_probe")}
    write_atomic(history,(old+[entry])[-120:])

def main():
    root=Path(os.getenv("STATE_DIR","/state"))
    rotation=0
    while True:
        try:
            broker=WebullBroker(root)
            report=run_cycle(root,broker,rotation)
            _persist(root,report)
            print("Webull scan",len(report.get("signals",[])),
                  "candidates",report.get("candidates",0),
                  "execution",report.get("execution_status"),flush=True)
        except Exception as exc:
            report={"updated_at":_now().isoformat(),"worker":"DEGRADED",
                "execution_status":"BLOCKED_"+_safe_public(exc),
                "execution_reason":"Broker or market data unavailable; no order placed",
                "live_orders_allowed":False}
            _persist(root,report)
            print("Webull scan blocked",_safe_public(exc),flush=True)
        rotation=(rotation+MAX_STOCKS_PER_CYCLE)%len(STOCK_DISCOVERY_UNIVERSE)
        time.sleep(90)

if __name__=="__main__":main()
