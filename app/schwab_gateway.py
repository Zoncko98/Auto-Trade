"""Schwab Trader API integration groundwork.

No live execution is enabled by importing this module. Account authorization,
account permissions, cash reconciliation and a separate explicit live activation
are required before order submission is permitted.

HTTP calls use the published Schwab Trader API host, disable redirects, and
never log or disclose OAuth access/refresh tokens.
"""
from __future__ import annotations

import base64
import json
import math
import re
import ssl
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPSHandler, ProxyHandler, HTTPRedirectHandler

API_HOST = "https://api.schwabapi.com"
AUTH_URL = API_HOST + "/v1/oauth/authorize"
TOKEN_URL = API_HOST + "/v1/oauth/token"
TRADER_HOST = API_HOST + "/trader/v1"
MARKET_HOST = API_HOST + "/marketdata/v1"
SYMBOL = re.compile(r"^[A-Z][A-Z0-9.]{0,9}$")


class BrokerUnavailable(RuntimeError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _http(url: str, method: str, data: bytes | None, headers: dict, timeout: float=8) -> tuple[int, dict, dict]:
    if not url.startswith(API_HOST + "/"):
        raise BrokerUnavailable("Blocked non-Schwab API host")
    opener = build_opener(ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context()), NoRedirect())
    req = Request(url, data=data, method=method, headers=headers)
    try:
        with opener.open(req, timeout=timeout) as response:
            raw=response.read(262_145)
            if len(raw)>262_144:
                raise BrokerUnavailable("Oversized Schwab response")
            if raw:
                return response.status, json.loads(raw), dict(response.headers.items())
            return response.status, {}, dict(response.headers.items())
    except Exception as exc:
        raise BrokerUnavailable("Schwab connection failed: " + type(exc).__name__) from None


def authorization_url(app_key: str, redirect_uri: str, state: str) -> str:
    """Public OAuth authorization URL; never accept brokerage passwords."""
    if not isinstance(app_key, str) or not 12<=len(app_key)<=160:
        raise ValueError("Invalid Schwab app key")
    if not isinstance(redirect_uri, str) or len(redirect_uri)>400:
        raise ValueError("Invalid redirect URI")
    parsed=urlsplit(redirect_uri)
    if parsed.scheme!="https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("Schwab callback must be an HTTPS URI registered with Schwab")
    if not isinstance(state,str) or not 16<=len(state)<=150 or not re.fullmatch(r"[A-Za-z0-9_-]+",state):
        raise ValueError("Invalid OAuth state")
    return AUTH_URL + "?" + urlencode({
        "client_id":app_key,"redirect_uri":redirect_uri,
        "response_type":"code","state":state,
    })


def exchange_authorization_code(app_key: str, app_secret: str, redirect_uri: str, code: str) -> dict:
    if not isinstance(code,str) or not 8<=len(code)<=4096:
        raise ValueError("Invalid OAuth authorization code")
    if not isinstance(app_secret,str) or not 12<=len(app_secret)<=1024:
        raise ValueError("Invalid application secret")
    # Validate callback and app key before making any request.
    authorization_url(app_key,redirect_uri,"valid-state-value-123456")
    auth=base64.b64encode((app_key+":"+app_secret).encode()).decode()
    data=urlencode({
        "grant_type":"authorization_code",
        "code":code,"redirect_uri":redirect_uri
    }).encode()
    status,body,_=_http(TOKEN_URL,"POST",data,{
        "Authorization":"Basic "+auth,
        "Content-Type":"application/x-www-form-urlencoded",
        "Accept":"application/json",
    })
    if status!=200 or not body.get("access_token") or not body.get("refresh_token"):
        raise BrokerUnavailable("Schwab token exchange incomplete")
    return body


def parse_settled_cash(account: dict) -> Decimal:
    """Fail closed if Schwab does not explicitly identify settled cash.

    Some Schwab account types expose several available-funds fields. Only
    values explicitly documented as settled cash may be used by this bot.
    No fallback to buyingPower, availableFunds or margin availability.
    """
    account_block=account.get("securitiesAccount",{})
    if not isinstance(account_block,dict):
        raise BrokerUnavailable("Unexpected Schwab account structure")
    balances=account_block.get("currentBalances") or {}
    value=balances.get("cashAvailableForTrading")
    if value is None:
        raise BrokerUnavailable("Settled cash not verified: no cash balance")
    try:
        amt=Decimal(str(value))
    except (ValueError,InvalidOperation) as exc:
        raise BrokerUnavailable("Cash balance is invalid") from None
    if not amt.is_finite() or amt < 0:
        raise BrokerUnavailable("Invalid cash balance")
    # This alone is not enough to prove settlement. The app must separately
    # reconcile the actual settled/unsettled status before live execution.
    return amt


@dataclass(frozen=True)
class LiveOrderIntent:
    symbol: str
    quantity: int
    limit_price: Decimal
    account_hash: str
    limit_notional_usd: Decimal = Decimal("100.00")

    def validate(self) -> Decimal:
        if not isinstance(self.symbol,str) or not SYMBOL.fullmatch(self.symbol):
            raise ValueError("Only uppercase equity ticker symbols are allowed")
        if type(self.quantity) is not int or not 1<=self.quantity<=10000:
            raise ValueError("Whole-share quantity is required")
        if not isinstance(self.limit_price,Decimal) or not self.limit_price.is_finite():
            raise ValueError("Invalid limit price")
        if self.limit_price<=0 or self.limit_price.as_tuple().exponent < -2:
            raise ValueError("Limit price must be positive with at most two decimal places")
        if not isinstance(self.account_hash,str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}",self.account_hash):
            raise ValueError("Invalid account hash")
        amount=self.limit_price*self.quantity
        if (not isinstance(self.limit_notional_usd,Decimal) or
                not self.limit_notional_usd.is_finite() or
                self.limit_notional_usd<=0 or self.limit_notional_usd>Decimal("100.00")):
            raise ValueError("Live trading capital cap must not exceed $100")
        if amount<=0 or amount>self.limit_notional_usd:
            raise ValueError("Order exceeds configured $100 capital cap")
        return amount

    def payload(self) -> dict:
        self.validate()
        return {
            "orderType":"LIMIT",
            "session":"NORMAL",
            "duration":"DAY",
            "orderStrategyType":"SINGLE",
            "price":format(self.limit_price,".2f"),
            "orderLegCollection":[{
                "instruction":"BUY",
                "quantity":self.quantity,
                "instrument":{"symbol":self.symbol,"assetType":"EQUITY"},
            }],
        }


class SchwabBrokerGateway:
    def __init__(self, access_token: str, account_hash: str, live_armed: bool=False):
        if not isinstance(access_token,str) or len(access_token)<12:
            raise ValueError("Missing Schwab access token")
        self._token=access_token
        self._account_hash=account_hash
        self._live_armed=bool(live_armed)

    def _headers(self) -> dict:
        return {"Authorization":"Bearer "+self._token,"Accept":"application/json"}

    def accounts(self) -> list:
        status,data,_=_http(TRADER_HOST+"/accounts","GET",None,self._headers())
        if status!=200 or not isinstance(data,list):
            raise BrokerUnavailable("Schwab account response invalid")
        return data

    def account_hashes(self) -> list:
        status,data,_=_http(TRADER_HOST+"/accounts/accountNumbers","GET",None,self._headers())
        if status!=200 or not isinstance(data,list):
            raise BrokerUnavailable("Schwab account hash mapping invalid")
        return data

    def quote(self, symbol: str) -> dict:
        if not SYMBOL.fullmatch(symbol):
            raise ValueError("Unsupported ticker symbol")
        status,data,_=_http(MARKET_HOST+"/quotes?"+urlencode({"symbols":symbol}),"GET",None,self._headers())
        if status!=200 or not isinstance(data,dict) or symbol not in data:
            raise BrokerUnavailable("Schwab quote unavailable")
        return data[symbol]

    def place_order(self, intent: LiveOrderIntent):
        """Deliberately disabled until brokerage reconciliation is implemented.

        No method in the worker calls this. Do not bypass this guard by setting
        an environment variable; live execution requires a separately reviewed
        order-state machine, broker account authorization, and exact settlement.
        """
        intent.validate()
        if not self._live_armed:
            raise BrokerUnavailable("Live orders are not armed")
        raise BrokerUnavailable(
            "Live order submission remains locked until broker account, settled cash, "
            "execution reconciliation and duplicate-order controls are implemented"
        )


@dataclass(frozen=True)
class LiveRiskEnvelope:
    """Aggregate $100 safety budget for a future live execution gateway.

    Caller must supply authoritative, reconciled broker data. This function
    is not yet connected to a Schwab account or live order submission.
    """
    initial_live_cap: Decimal = Decimal("100.00")
    maximum_position_fraction: Decimal = Decimal("0.25")
    maximum_daily_drawdown: Decimal = Decimal("5.00")
    maximum_open_positions: int = 3

    def check_candidate(
        self, intent: LiveOrderIntent, *,
        broker_settled_cash: Decimal,
        aggregate_open_exposure: Decimal,
        aggregate_pending_buy_notional: Decimal,
        current_daily_drawdown: Decimal,
        open_position_count: int,
        broker_account_reconciled: bool,
        normal_market_session: bool,
    ) -> Decimal:
        if not broker_account_reconciled:
            raise BrokerUnavailable("Broker account reconciliation is required")
        if not normal_market_session:
            raise BrokerUnavailable("Broker verified market session is required")
        if type(open_position_count) is not int or open_position_count < 0:
            raise BrokerUnavailable("Invalid open position count")
        if open_position_count >= self.maximum_open_positions:
            raise BrokerUnavailable("Live open-position limit reached")
        for amount in (
            self.initial_live_cap, self.maximum_position_fraction,
            self.maximum_daily_drawdown, broker_settled_cash,
            aggregate_open_exposure, aggregate_pending_buy_notional,
            current_daily_drawdown,
        ):
            if not isinstance(amount, Decimal) or not amount.is_finite():
                raise BrokerUnavailable("Broker monetary inputs must be verified finite Decimals")
        if self.initial_live_cap <= 0 or self.initial_live_cap > Decimal("100.00"):
            raise BrokerUnavailable("Live capital cap cannot exceed $100")
        if not Decimal("0") < self.maximum_position_fraction <= Decimal("1"):
            raise BrokerUnavailable("Invalid position risk fraction")
        if self.maximum_daily_drawdown <= 0 or self.maximum_daily_drawdown > self.initial_live_cap:
            raise BrokerUnavailable("Invalid daily loss threshold")
        if any(x < 0 for x in (
            broker_settled_cash, aggregate_open_exposure,
            aggregate_pending_buy_notional, current_daily_drawdown,
        )):
            raise BrokerUnavailable("Negative broker exposure or cash")
        if current_daily_drawdown >= self.maximum_daily_drawdown:
            raise BrokerUnavailable("Daily loss threshold reached")
        requested=intent.validate()
        if requested > broker_settled_cash:
            raise BrokerUnavailable("Insufficient verified settled cash")
        if requested > self.initial_live_cap * self.maximum_position_fraction:
            raise BrokerUnavailable("Order exceeds configured position percentage")
        if aggregate_open_exposure + aggregate_pending_buy_notional + requested > self.initial_live_cap:
            raise BrokerUnavailable("Aggregate live capital budget exhausted")
        return requested
