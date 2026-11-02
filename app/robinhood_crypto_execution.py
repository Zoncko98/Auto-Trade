"""Robinhood Crypto v2 live-order adapter. Never submits without explicit per-account enablement."""
from __future__ import annotations

import base64
import json
import re
import ssl
import uuid
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, ProxyHandler, HTTPSHandler, HTTPRedirectHandler

from robinhood_crypto_gateway import (
    RobinhoodCryptoAdapter, RobinhoodUnavailable, NoRedirect, HOST, PAIR, ACCOUNT
)

class RobinhoodCryptoTradingAdapter(RobinhoodCryptoAdapter):
    """Adapter for the shared worker; live execution is disabled by default.

    The caller must persist an idempotency/order ledger and provide risk approvals.
    This module does not spawn a trading engine.
    """

    def __init__(self, api_key, private_key_b64, *, live_enabled=False,
                 allowed_accounts=(), max_order_usd="50", write_transport=None,
                 transport=None, clock=None):
        super().__init__(api_key, private_key_b64, transport=transport, clock=clock)
        self.live_enabled = live_enabled is True
        self.allowed_accounts = frozenset(allowed_accounts)
        self.max_order_usd = self._positive(max_order_usd)
        self._write_transport = write_transport or self._post_http

    @staticmethod
    def _positive(value):
        if not isinstance(value, (str, int, Decimal)) or isinstance(value, bool):
            raise ValueError("Amount must be decimal text")
        try:
            amount = Decimal(str(value))
        except InvalidOperation:
            raise ValueError("Invalid amount") from None
        if not amount.is_finite() or amount <= 0:
            raise ValueError("Amount must be positive")
        return amount

    def _permit(self, account_ref):
        if not self.live_enabled:
            raise RobinhoodUnavailable("Robinhood live trading not enabled")
        if not isinstance(account_ref, str) or not ACCOUNT.fullmatch(account_ref):
            raise RobinhoodUnavailable("Invalid account")
        if account_ref not in self.allowed_accounts:
            raise RobinhoodUnavailable("Account not explicitly authorized")
        account = self.balances(account_ref)
        if account.get("status") != "active" or account.get("is_api_tradable") is not True:
            raise RobinhoodUnavailable("Account not API-tradable")
        return account

    def _post_headers(self, path, body):
        timestamp = str(int(self._clock()))
        signed = (self._api_key + timestamp + path + "POST" + body).encode("utf-8")
        signature = base64.b64encode(self._signer.sign(signed)).decode("ascii")
        return {"x-api-key": self._api_key, "x-signature": signature,
                "x-timestamp": timestamp, "Content-Type": "application/json"}

    @staticmethod
    def _post_http(path, body, headers):
        req = Request(HOST + path, data=body.encode("utf-8"), method="POST", headers=headers)
        opener = build_opener(ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context()), NoRedirect())
        try:
            with opener.open(req, timeout=12) as response:
                payload = response.read(1048577)
                if len(payload) > 1048576:
                    raise RobinhoodUnavailable("Oversized response")
                return json.loads(payload) if payload else {"status": "accepted"}
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            # Never log credentials, signed headers, or possibly sensitive response body.
            raise RobinhoodUnavailable("Robinhood write request failed: " + type(exc).__name__) from None

    def submit_order(self, account_ref, intent):
        self._permit(account_ref)
        if not isinstance(intent, dict) or intent.get("risk_approved") is not True or intent.get("operator_approved") is not True:
            raise RobinhoodUnavailable("Independent risk and operator approvals required")
        if intent.get("type") != "limit" or intent.get("side") not in ("buy", "sell"):
            raise RobinhoodUnavailable("Only limit orders permitted")
        symbol = intent.get("symbol")
        if not isinstance(symbol, str) or not PAIR.fullmatch(symbol):
            raise ValueError("Invalid crypto pair")
        try:
            client_id = str(uuid.UUID(intent.get("client_order_id", "")))
        except (ValueError, TypeError, AttributeError):
            raise RobinhoodUnavailable("Stable client_order_id UUID required") from None
        quantity = self._positive(intent.get("asset_quantity"))
        price = self._positive(intent.get("limit_price"))
        if quantity * price > self.max_order_usd:
            raise RobinhoodUnavailable("Order exceeds account limit")
        # Explicit account-level preflight to prevent accidental use of another broker.
        body = {
            "client_order_id": client_id,
            "side": intent["side"],
            "type": "limit",
            "symbol": symbol,
            "limit_order_config": {
                "asset_quantity": str(quantity),
                "limit_price": str(price),
                "time_in_force": "gtc",
            },
        }
        path = "/api/v2/crypto/trading/orders/?" + urlencode({"account_number": account_ref})
        serialized = json.dumps(body, separators=(",", ":"))
        return self._write_transport(path, serialized, self._post_headers(path, serialized))

    def cancel_order(self, account_ref, order_ref):
        self._permit(account_ref)
        try:
            order_id = str(uuid.UUID(order_ref))
        except (ValueError, TypeError, AttributeError):
            raise RobinhoodUnavailable("Invalid order UUID") from None
        # Cancel endpoint has no body; still signs the complete path and POST method.
        path = "/api/v2/crypto/trading/orders/" + order_id + "/cancel/"
        return self._write_transport(path, "", self._post_headers(path, ""))
