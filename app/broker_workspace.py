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
    robinhood=BrokerCapability(
        id="robinhood_crypto",name="Robinhood Crypto",
        integration_status="crypto_only",
        auth_method="Official Robinhood Crypto API key authentication",
        assets=("crypto",),
        official_account_access=True,official_market_data=True,official_order_execution=True,
        app_account_connected=False,app_orders_supported=False,
        setup_requirement="Official published API covers crypto, not general Robinhood stock-order automation; crypto adapter must be implemented separately.",
        description="Robinhood's published developer trading API supports crypto account data and crypto orders in eligible US accounts. Stock brokerage automation is not offered here.",
        docs_url="https://docs.robinhood.com/",
        phase="research")
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
    return [asdict(p) for p in (schwab,webull,alpaca,robinhood,ibkr)]

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
