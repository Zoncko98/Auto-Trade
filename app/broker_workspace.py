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
        return {"worker":{k:worker.get(k) for k in
                    ("updated_at","worker","quotes_checked","pairs_checked",
                     "pending_order_intents","execution_status","live_orders_allowed",
                     "last_order_confirmed","reason")},
                "provider":"robinhood_crypto","credentials_saved":credential_saved,"connected":True,
                "order_execution_enabled":False,
                "execution_status":"NOT_INTEGRATED",
                "execution_reason":"Robinhood Crypto account connectivity is read-only; autonomous strategy, order reconciliation, and account-specific risk controls are not connected.",
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
    """Read-only portfolio overview; no credentials or order submission exposed."""
    from robinhood_crypto_gateway import RobinhoodUnavailable
    try:
        client=_robinhood_client(state)
        accounts=client.list_accounts()
        holdings=[]
        orders=[]
        for account in accounts[:6]:
            if not isinstance(account,dict): continue
            account_ref=account.get("account_number")
            if not isinstance(account_ref,str):continue
            for item in client.positions(account_ref):
                if isinstance(item,dict): holdings.append(item)
            for item in client.orders(account_ref):
                if isinstance(item,dict): orders.append(item)
        # Only counts are returned until an account-scoped holdings schema
        # and privacy filters have been validated.
        return {"available":True,"position_count":len(holdings),
                "order_count":len(orders)}
    except (OSError,ValueError,KeyError,TypeError,RobinhoodUnavailable):
        return {"available":False,"reason":"Robinhood account portfolio request failed"}
