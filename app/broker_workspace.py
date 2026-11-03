"""Broker provider contracts and workspace discovery.

This is a brokerage capability layer, not a way to bypass broker authorization.
Only the existing explicitly approved Schwab worker can submit orders. Adding a
provider definition never authorizes trades on it.
"""
from __future__ import annotations
from dataclasses import dataclass,asdict
from pathlib import Path
from typing import Protocol,Mapping,Any
import json
import os

@dataclass(frozen=True)
class BrokerCapability:
    id: str
    name: str
    integration_status: str
    auth_method: str
    assets: tuple[str,...]
    official_account_access: bool
    official_market_data: bool
    official_order_execution: bool
    app_account_connected: bool
    app_orders_supported: bool
    setup_requirement: str
    description: str
    docs_url: str
    phase: str

class BrokerAdapter(Protocol):
    """Common interface future provider adapters must implement and test."""
    provider_id: str
    def list_accounts(self) -> list[Mapping[str,Any]]: ...
    def balances(self,account_ref:str) -> Mapping[str,Any]: ...
    def positions(self,account_ref:str) -> list[Mapping[str,Any]]: ...
    def quote(self,symbol:str) -> Mapping[str,Any]: ...
    def orders(self,account_ref:str) -> list[Mapping[str,Any]]: ...
    def submit_order(self,account_ref:str,intent:Mapping[str,Any]) -> Mapping[str,Any]: ...
    def cancel_order(self,account_ref:str,order_ref:str) -> Mapping[str,Any]: ...

class BrokerNotAvailable(RuntimeError):pass

class UnavailableBrokerAdapter:
    """Explicit fail-closed placeholders; never make remote API requests."""
    def __init__(self,provider_id):
        if provider_id not in ("webull","alpaca","robinhood_crypto","interactive_brokers"):
            raise ValueError("Unknown provider")
        self.provider_id=provider_id
    def _not_ready(self):
        raise BrokerNotAvailable("This provider is not connected through a validated Auto Trader adapter.")
    def list_accounts(self):self._not_ready()
    def balances(self,account_ref):self._not_ready()
    def positions(self,account_ref):self._not_ready()
    def quote(self,symbol):self._not_ready()
    def orders(self,account_ref):self._not_ready()
    def submit_order(self,account_ref,intent):self._not_ready()
    def cancel_order(self,account_ref,order_ref):self._not_ready()

def providers(state):
    """Status is read-only; neither keys nor OAuth authorization codes are returned."""
    state=Path(state)
    schwab_token=(state/"schwab_token.json").is_file()
    # A saved token is not proof of a successful current API call; say so.
    schwab=BrokerCapability(
        id="schwab",name="Charles Schwab",
        integration_status="authorization_saved" if schwab_token else "not_connected",
        auth_method="OAuth 2.0 — Schwab official sign-in",
        assets=("US stocks","ETFs"),
        official_account_access=True,official_market_data=True,official_order_execution=True,
        app_account_connected=schwab_token,app_orders_supported=schwab_token,
        setup_requirement=("Broker authorization file saved; verify account freshness in Schwab settings"
                           if schwab_token else "Open Integrations to connect your Schwab developer app and approve OAuth"),
        description="Existing live worker, read-only quotes, order journal and brokerage positions; limited to conservative cash-only US equities and ETFs.",
        docs_url="https://developer.schwab.com/",
        phase="active")
    paper=BrokerCapability(
        id="paper",name="Paper Trading",integration_status="virtual_account",
        auth_method="No brokerage authorization required",
        assets=("US stocks","ETFs"),official_account_access=False,
        official_market_data=False,official_order_execution=False,
        app_account_connected=True,app_orders_supported=True,
        setup_requirement="Virtual account uses a configured read-only market data source",
        description="One strategy engine, simulated fills and isolated account balances; no real orders.",
        docs_url="https://github.com/Zoncko98/Auto-Trade",phase="active")
    webull=BrokerCapability(
        id="webull",name="Webull",integration_status="approval_required",
        auth_method="Connect API OAuth 2.0 (third-party); individual OpenAPI uses approved app keys",
        assets=("US stocks","ETFs","options","futures","crypto"),
        official_account_access=True,official_market_data=True,official_order_execution=True,
        app_account_connected=False,app_orders_supported=False,
        setup_requirement="Webull Connect API application/partner approval, credentials and sandbox testing are required before connecting users",
        description="Official Webull APIs support account access, data and trading. Auto Trader's account linking and order adapter are being developed; no Webull credentials are requested yet.",
        docs_url="https://developer.webull.com/apis/docs/connect-api/about-connect-api/",
        phase="planned")
    alpaca=BrokerCapability(
        id="alpaca",name="Alpaca",integration_status="approval_required",
        auth_method="OAuth 2.0 for third-party account connection; personal API keys for own accounts",
        assets=("US stocks","ETFs","crypto"),
        official_account_access=True,official_market_data=True,official_order_execution=True,
        app_account_connected=False,app_orders_supported=False,
        setup_requirement="Register an OAuth application; live access for third-party customers requires approval. Paper and live authorization must remain separate.",
        description="Good candidate for integrated paper brokerage and equities trading after account authorization and order reconciliation tests.",
        docs_url="https://docs.alpaca.markets/us/docs/about-connect-api",
        phase="planned")
    # Connection presence is not proof of a successful authentication.
    rh_credential_ready=((state/"config"/"robinhood_crypto.json").is_file() or
                         bool(os.getenv("ROBINHOOD_CRYPTO_API_KEY") and
                              os.getenv("ROBINHOOD_CRYPTO_PRIVATE_KEY_B64")))
    robinhood=BrokerCapability(
        id="robinhood_crypto",name="Robinhood Crypto",
        integration_status="configuration_saved" if rh_credential_ready else "credentials_required",
        auth_method="Official Robinhood Crypto API key authentication",
        assets=("crypto",),
        official_account_access=True,official_market_data=True,official_order_execution=True,
        app_account_connected=False,app_orders_supported=False,
        setup_requirement=("Credentials loaded; test authenticated account access before enabling trading."
                           if rh_credential_ready else
                           "Install Robinhood Crypto API key and private signing key in the TrueNAS app secrets; no credentials belong in Git."),
        description="Robinhood's published developer trading API supports crypto account data and crypto orders in eligible US accounts. Stock brokerage automation is not offered here.",
        docs_url="https://docs.robinhood.com/",
        phase="integration")
    ibkr=BrokerCapability(
        id="interactive_brokers",name="Interactive Brokers",
        integration_status="integration_required",
        auth_method="IB Gateway/TWS or Web API; OAuth requires eligible partner registration",
        assets=("US stocks","global stocks","ETFs","options","futures"),
        official_account_access=True,official_market_data=True,official_order_execution=True,
        app_account_connected=False,app_orders_supported=False,
        setup_requirement="Choose an authorized IB Gateway/TWS or approved Web API OAuth integration; account and data entitlements vary.",
        description="Professional multi-market broker with API options. Needs session, account-selection and entitlement handling before live orders.",
        docs_url="https://www.interactivebrokers.com/docs/",
        phase="planned")
    return [asdict(p) for p in (schwab,paper,webull,alpaca,robinhood,ibkr)]

def workspace_summary(state):
    items=providers(state)
    return {
        "schema":1,
        "workspace":"multi_broker",
        "live_execution_broker":"schwab",
        "live_execution_policy":"Only the existing Schwab worker can place live orders; all other adapters fail closed.",
        "broker_account_aggregation":"not_enabled",
        "brokers":items,
    }

def _robinhood_client(state):
    """Choose server-side installed credentials, otherwise optional environment secrets."""
    from robinhood_crypto_gateway import RobinhoodCryptoAdapter
    try:
        return RobinhoodCryptoAdapter.from_state(state)
    except FileNotFoundError:
        return RobinhoodCryptoAdapter.from_environment()




def _pending_order_diagnostics(state,client):
    """Expose one safe, read-only view of the duplicate-order lock."""
    from datetime import datetime,timezone
    from robinhood_order_journal import OrderJournal,UnreconciledOrder
    try:
        pending=OrderJournal(state).pending()
    except (OSError,ValueError,TypeError,UnreconciledOrder):
        return []
    result=[]
    for row in pending[:5]:
        if not isinstance(row,dict):continue
        account=row.get("account")
        client_id=row.get("client_order_id")
        broker_match=None
        broker_error=None
        if isinstance(account,str) and isinstance(client_id,str):
            try:
                matches=[o for o in client.orders(account)
                         if isinstance(o,dict) and o.get("client_order_id")==client_id]
                if len(matches)==1:broker_match=matches[0]
                elif len(matches)>1:broker_error="Multiple broker records matched this client order id"
                else:broker_error="No matching Robinhood order found yet"
            except Exception:
                broker_error="Robinhood order lookup unavailable"
        created=row.get("created_at")
        first_miss=row.get("first_reconcile_miss_at")
        broker_created=broker_match.get("created_at") if isinstance(broker_match,dict) else None
        reference=created or first_miss or broker_created
        age_seconds=None
        if isinstance(reference,str):
            try:
                stamp=datetime.fromisoformat(reference.replace("Z","+00:00"))
                if stamp.tzinfo is not None:
                    age_seconds=max(0,int((datetime.now(timezone.utc)-stamp).total_seconds()))
            except (ValueError,TypeError,AttributeError):
                pass
        result.append({
            "symbol":row.get("symbol"),
            "side":row.get("side"),
            "quantity":row.get("quantity"),
            "limit_price":row.get("limit_price"),
            "local_status":row.get("status"),
            "created_at":created,
            "age_seconds":age_seconds,
            "client_order_id":client_id,
            "broker_matched":broker_match is not None,
            "broker_state":(broker_match.get("state",broker_match.get("status"))
                            if isinstance(broker_match,dict) else None),
            "broker_order_id":broker_match.get("id") if isinstance(broker_match,dict) else None,
            "broker_created_at":broker_created,
            "broker_updated_at":broker_match.get("updated_at") if isinstance(broker_match,dict) else None,
            "filled_asset_quantity":broker_match.get("filled_asset_quantity") if isinstance(broker_match,dict) else None,
            "average_price":broker_match.get("average_price") if isinstance(broker_match,dict) else None,
            "broker_lookup_detail":broker_error,
            "reconcile_miss_count":int(row.get("reconcile_miss_count") or 0),
            "first_reconcile_miss_at":row.get("first_reconcile_miss_at"),
            "last_reconcile_check_at":row.get("last_reconcile_check_at"),
            "manual_resolution_eligible":(
                broker_match is None and not row.get("broker_order_id")
                and int(row.get("reconcile_miss_count") or 0)>=10),
        })
    return result

def resolve_robinhood_orphan(state,payload,client=None):
    """Resolve only a proven local orphan after a fresh authoritative broker-history miss."""
    from robinhood_order_journal import OrderJournal,UnreconciledOrder
    from robinhood_crypto_gateway import RobinhoodUnavailable
    if not isinstance(payload,dict) or set(payload)!={"client_order_id"}:
        raise ValueError("Pending order identifier required")
    client_id=payload.get("client_order_id")
    if not isinstance(client_id,str) or not client_id:
        raise ValueError("Pending order identifier required")
    journal=OrderJournal(state)
    matches=[row for row in journal.pending()
             if isinstance(row,dict) and row.get("client_order_id")==client_id]
    if len(matches)!=1:
        raise ValueError("Pending order is no longer available")
    row=matches[0]
    misses=int(row.get("reconcile_miss_count") or 0)
    if misses<10:
        raise ValueError("At least 10 successful Robinhood history misses are required")
    if row.get("broker_order_id"):
        raise ValueError("Robinhood order ID exists; manual orphan resolution is not permitted")
    account=row.get("account")
    if not isinstance(account,str):
        raise ValueError("Pending order account unavailable")
    client=client or _robinhood_client(state)
    broker_rows=client.orders(account)
    broker_matches=[item for item in broker_rows if isinstance(item,dict)
                    and item.get("client_order_id")==client_id]
    if broker_matches:
        journal.reconcile(account,broker_rows)
        raise ValueError("Robinhood now reports this order; reconciliation must use broker state")
    journal.mark_submission_rejected(
        client_id,
        "Operator resolved local orphan after "+str(misses)+
        " prior successful history misses and a fresh Robinhood history check found no order")
    return {"resolved":True,"client_order_id":client_id,
            "reason":"Fresh Robinhood order history confirmed no matching order; duplicate-order lock released"}

def robinhood_status(state):
    """Verify broker account access, never sending a secret to the browser."""
    from robinhood_crypto_gateway import RobinhoodUnavailable
    state=Path(state)
    credential_saved=((state/"config"/"robinhood_crypto.json").is_file() or
                      bool(os.getenv("ROBINHOOD_CRYPTO_API_KEY") and os.getenv("ROBINHOOD_CRYPTO_PRIVATE_KEY_B64")))
    try:
        accounts = _robinhood_client(state).list_accounts()
        try:
            worker=json.loads((state/"robinhood"/"worker_status.json").read_text())
        except (OSError,ValueError,TypeError):
            worker={"execution_status":"NOT_ARMED","worker":"not_started"}
        from robinhood_policy import read_policy
        try:policy=read_policy(state)
        except (ValueError,OSError):policy={"enabled":False}
        armed=policy.get("enabled") is True
        from datetime import datetime,timezone
        try:
            last=datetime.fromisoformat(worker.get("updated_at","").replace("Z","+00:00"))
            fresh=last.tzinfo is not None and 0<=(datetime.now(timezone.utc)-last).total_seconds()<600
        except (ValueError,TypeError,AttributeError):fresh=False
        pending_orders=_pending_order_diagnostics(state,_robinhood_client(state))
        pending=len(pending_orders) if pending_orders else int(worker.get("pending_order_intents") or 0)
        if not armed:
            effective="PAUSED"; detail="Live order permission is off"
        elif not fresh or worker.get("worker")!="monitoring":
            effective="WORKER_OFFLINE"; detail="Trading policy armed, but a fresh crypto worker heartbeat is missing"
        elif pending>0:
            effective="RECONCILIATION_PENDING"; detail="Unresolved bot order intent requires broker reconciliation"
        elif worker.get("execution_status") in ("ORDER_ACCEPTED","SUBMITTED_UNCONFIRMED","SELL_ORDER_ACCEPTED","SELL_SUBMITTED_UNCONFIRMED"):
            effective="ORDER_PENDING"; detail="Broker order submitted; confirm fill separately"
        elif worker.get("risk_check")!="ACCOUNT_PREFLIGHT_PASSED_SIGNAL_NOT_CHECKED":
            effective="RISK_BLOCKED"; detail="Risk preflight: "+str(worker.get("risk_check") or "unknown")
        elif worker.get("ai_review_status")=="VETO_OR_UNAVAILABLE":
            effective="AI_VETO"; detail="Latest AI review did not approve a buy"
        else:
            effective="ARMED_WAITING_SIGNAL"; detail="Live permission enabled; scanning for a qualifying technical and AI-approved opportunity"
        try:
            history=json.loads((state/"robinhood"/"decision_history.json").read_text())
            if not isinstance(history,list):history=[]
        except (OSError,ValueError,TypeError):history=[]
        history=[{k:row.get(k) for k in ("at","signal","ai_review_status","ai_connection_status","ai_model",
                                    "ai_reason","execution_status","execution_reason","risk_check",
                                    "exit_candidate_symbol","exit_momentum_pct","exit_spread_pct",
                                    "exit_signal_reason","entry_candidate_symbol","entry_momentum_pct",
                                    "market_data_source","coinbase_feed","coinbase_live_pairs",
                                    "coinbase_scanned_pairs","pairs_checked","quotes_checked",
                                    "signal_diagnostics","top_entry_observations",
                                    "ranked_entry_candidates")}
                 for row in history[-100:] if isinstance(row,dict)]
        return {"effective_state":effective,"effective_detail":detail,"worker_fresh":fresh,
                "decision_evidence":history,"pending_orders":pending_orders,
                "policy_enabled":armed,"worker":{k:worker.get(k) for k in
                    ("updated_at","worker","quotes_checked","pairs_checked","universe_size","scan_batch","coinbase_feed","coinbase_live_pairs","coinbase_scanned_pairs","market_data_source",
                     "pending_order_intents","risk_check", "last_signal","observations","signal_diagnostics","ai_review_status","ai_connection_status","ai_model","ai_reason","execution_status","live_orders_allowed",
                      "last_order_confirmed","reason","execution_reason","exit_candidate_symbol",
                      "exit_momentum_pct","exit_spread_pct","exit_signal_reason",
                      "entry_candidate_symbol","entry_momentum_pct","ranked_entry_candidates",
                      "top_entry_observations","bot_open_positions","daily_realized_pnl_usd")},
                "provider":"robinhood_crypto","credentials_saved":credential_saved,"connected":True,
                "order_execution_enabled":armed,
                "execution_status":worker.get("execution_status","NOT_ARMED"),
                "execution_reason":"Account policy armed, subject to strategy and real-time broker preflight" if armed else "Robinhood trading permission disabled or not configured",
                "accounts":[{"account_number":str(a.get("account_number","")),
                             "status":str(a.get("status","unknown")),
                             "buying_power":str(a.get("buying_power","")),
                             "buying_power_currency":str(a.get("buying_power_currency","")),
                             "is_api_tradable":a.get("is_api_tradable") is True}
                            for a in accounts if isinstance(a,dict)]}
    except (OSError,ValueError,KeyError,RobinhoodUnavailable,TypeError):
        return {"provider":"robinhood_crypto","credentials_saved":credential_saved,"connected":False,"order_execution_enabled":False,
                "reason":"Robinhood credentials missing or account authorization unsuccessful"}


def install_robinhood_credentials(state,payload):
    """CSRF-protected dashboard caller only. Install encrypted-in-transit credentials on disk."""
    import base64
    import json
    import os
    import secrets
    from pathlib import Path
    from robinhood_crypto_gateway import RobinhoodCryptoAdapter
    if not isinstance(payload,dict) or set(payload)!={"api_key","private_key_b64"}:
        raise ValueError("Robinhood key identifier and signing key required")
    api_key = payload["api_key"]
    private_key = payload["private_key_b64"]
    if not isinstance(api_key,str) or not api_key.startswith("rh-api-") or len(api_key)>200:
        raise ValueError("Invalid Robinhood API key identifier")
    if not isinstance(private_key,str) or len(private_key)>400:
        raise ValueError("Invalid signing key")
    private_key = private_key.strip()
    RobinhoodCryptoAdapter(api_key,private_key)
    target_dir=Path(state)/"config"
    target_dir.mkdir(mode=0o700,exist_ok=True)
    target=target_dir/"robinhood_crypto.json"
    temp=target_dir/(".robinhood-"+secrets.token_hex(12))
    fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(fd,"w") as writer:
            json.dump({"api_key":api_key,"private_key_b64":private_key},writer)
            writer.flush()
            os.fsync(writer.fileno())
        os.replace(temp,target)
    finally:
        try: temp.unlink()
        except FileNotFoundError: pass
    return {"saved":True,"connected":False,
            "message":"Credentials saved on the TrueNAS server. Verify the connection to activate account data."}


def robinhood_portfolio(state):
    """Broker holdings with conservatively verified USD marks and quantities."""
    from decimal import Decimal,InvalidOperation
    from robinhood_crypto_gateway import RobinhoodUnavailable
    from robinhood_portfolio_pnl import estimated_acquisition_cost,position_return
    def dec(x):
        try:
            v=Decimal(str(x))
            return v if v.is_finite() and v>=0 else None
        except (ValueError,TypeError,InvalidOperation):return None
    try:
        client=_robinhood_client(state)
        accounts=client.list_accounts()
        holdings=[]
        orders=0
        cash=Decimal("0")
        cash_verified=True
        for account in accounts[:6]:
            if not isinstance(account,dict):continue
            ref=account.get("account_number")
            if not isinstance(ref,str):continue
            amount=dec(account.get("buying_power"))
            if account.get("buying_power_currency")!="USD" or amount is None:
                cash_verified=False
            else:cash+=amount
            broker_orders=client.orders(ref)
            orders+=len(broker_orders)
            for item in client.positions(ref):
                if not isinstance(item,dict):continue
                code=item.get("asset_code")
                qty=dec(item.get("total_quantity"))
                available=dec(item.get("quantity_available_for_trading"))
                if not isinstance(code,str) or not code.isalnum() or len(code)>12 or qty is None:
                    continue
                symbol=code.upper()+"-USD"
                value=None
                midpoint=None
                if qty==0:value=Decimal("0")
                else:
                    try:
                        quote=client.quote(symbol)
                        rows=quote.get("results",[]) if isinstance(quote,dict) else []
                        matching=[v for v in rows if isinstance(v,dict) and v.get("symbol")==symbol]
                        if len(matching)==1:
                            bid=dec(matching[0].get("bid"));ask=dec(matching[0].get("ask"))
                            if bid is not None and ask is not None and 0<bid<=ask:
                                midpoint=(bid+ask)/2
                                value=qty*midpoint
                    except (RobinhoodUnavailable,ValueError,TypeError,KeyError):pass
                average_cost,basis_issue=estimated_acquisition_cost(symbol,qty,broker_orders)
                pnl,pnl_pct=position_return(qty,midpoint,average_cost)
                holdings.append({"symbol":symbol,"quantity":str(qty),
                    "available_quantity":str(available) if available is not None else None,
                    "current_price_usd":str(midpoint) if midpoint is not None else None,
                    "average_cost_usd":str(average_cost) if average_cost is not None else None,
                    "market_value_usd":str(value) if value is not None else None,
                    "unrealized_pnl_usd":str(pnl) if pnl is not None else None,
                    "unrealized_pnl_pct":str(pnl_pct) if pnl_pct is not None else None,
                    "cost_basis_source":"estimated_broker_fill_history" if average_cost is not None else "unavailable",
                    "cost_basis_note":basis_issue if basis_issue is not None else
                        "Estimated from accessible Robinhood filled orders; excludes purchase fees and transfers",
                    "valuation":"broker_bid_ask_midpoint" if value is not None else "unavailable"})
        priced=[h for h in holdings if h["market_value_usd"] is not None]
        unpriced=[h["symbol"] for h in holdings if h["market_value_usd"] is None]
        known_value=sum((Decimal(h["market_value_usd"]) for h in priced),Decimal("0"))
        total=cash+known_value if cash_verified and not unpriced else None
        priced_basis=[h for h in holdings if h["unrealized_pnl_usd"] is not None]
        known_pnl=sum((Decimal(h["unrealized_pnl_usd"]) for h in priced_basis),Decimal("0"))
        known_cost=sum((Decimal(h["average_cost_usd"])*Decimal(h["quantity"])
                         for h in priced_basis),Decimal("0"))
        all_covered=bool(holdings) and len(priced_basis)==len(holdings)
        known_pnl_pct=known_pnl/known_cost*100 if known_cost>0 else None
        return {"available":True,"position_count":len(holdings),"order_count":orders,
            "holdings":holdings,"cash_usd":str(cash) if cash_verified else None,
            "estimated_crypto_account_value_usd":str(total) if total is not None else None,
            "known_holdings_value_usd":str(known_value),
            "unpriced_holdings":unpriced,
            "known_unrealized_pnl_usd":str(known_pnl) if priced_basis else None,
            "known_unrealized_pnl_pct":str(known_pnl_pct) if known_pnl_pct is not None else None,
            "unrealized_pnl_usd":str(known_pnl) if all_covered else None,
            "unrealized_pnl_pct":str(known_pnl_pct) if all_covered and known_pnl_pct is not None else None,
            "pnl_covered_holdings":len(priced_basis),
            "pnl_total_holdings":len(holdings),
            "pnl_completeness":"complete_estimate" if all_covered else "partial_or_unavailable",
            "valuation_note":"Broker bid/ask midpoint estimates, not executable prices. Estimated P/L uses available filled-order history, not Robinhood's official average cost. Transfers, rewards, missing history and fees can change results. USD buying power may differ from cash balance."}
    except (OSError,ValueError,KeyError,TypeError,RobinhoodUnavailable):
        return {"available":False,"reason":"Robinhood account portfolio request failed"}
