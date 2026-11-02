"""Robinhood Crypto read-only adapter; order execution deliberately disabled."""
import base64
import json
import os
import re
import ssl
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler, ProxyHandler
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

HOST = "https://trading.robinhood.com"
PAIR = re.compile(r"^[A-Z0-9]{2,12}-USD$")
ACCOUNT = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

class RobinhoodUnavailable(RuntimeError):
    pass

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None

class RobinhoodCryptoAdapter:
    provider_id = "robinhood_crypto"
    def __init__(self, api_key, private_key_b64, transport=None, clock=None):
        if not isinstance(api_key, str) or not 1 <= len(api_key) <= 512:
            raise ValueError("Invalid API key")
        try:
            raw = base64.b64decode(private_key_b64, validate=True)
            if len(raw) != 32:
                raise ValueError("Invalid signing key")
            self._signer = Ed25519PrivateKey.from_private_bytes(raw)
        except (TypeError, ValueError):
            raise ValueError("Invalid signing key") from None
        self._api_key = api_key
        self._transport = transport or self._http
        self._clock = clock or time.time

    @classmethod
    def from_environment(cls):
        return cls(os.getenv("ROBINHOOD_CRYPTO_API_KEY", ""),
                   os.getenv("ROBINHOOD_CRYPTO_PRIVATE_KEY_B64", ""))

    def _headers(self, path):
        stamp = str(int(self._clock()))
        signature = self._signer.sign((self._api_key + stamp + path + "GET").encode())
        return {"x-api-key": self._api_key, "x-timestamp": stamp,
                "x-signature": base64.b64encode(signature).decode(), "Accept": "application/json"}

    @staticmethod
    def _http(path, headers):
        request = Request(HOST + path, headers=headers, method="GET")
        opener = build_opener(ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context()), NoRedirect())
        try:
            with opener.open(request, timeout=10) as response:
                raw = response.read(1048577)
                if len(raw) > 1048576:
                    raise RobinhoodUnavailable("Response too large")
                data = json.loads(raw)
                if not isinstance(data, dict):
                    raise RobinhoodUnavailable("Invalid API response")
                return data
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            raise RobinhoodUnavailable("Robinhood request failed: " + type(exc).__name__) from None

    def _get(self, path, params=None):
        if not path.startswith("/api/v2/crypto/") or "?" in path or "#" in path:
            raise ValueError("Unsupported path")
        if params:
            path += "?" + urlencode(params)
        data = self._transport(path, self._headers(path))
        if not isinstance(data, dict):
            raise RobinhoodUnavailable("Invalid API response")
        return data

    @staticmethod
    def _results(data):
        value = data.get("results")
        if not isinstance(value, list):
            raise RobinhoodUnavailable("Results missing")
        return value

    def _pages(self, path, params=None):
        items = []
        cursor = None
        seen = set()
        for _ in range(50):
            query = dict(params or {})
            if cursor:
                query["cursor"] = cursor
            data = self._get(path, query)
            items.extend(self._results(data))
            next_url = data.get("next")
            if not next_url:
                return items
            from urllib.parse import urlsplit, parse_qs
            parsed = urlsplit(next_url)
            if parsed.scheme != "https" or parsed.netloc != "trading.robinhood.com" or parsed.path != path:
                raise RobinhoodUnavailable("Invalid pagination destination")
            values = parse_qs(parsed.query).get("cursor", [])
            if len(values) != 1 or not values[0] or values[0] in seen:
                raise RobinhoodUnavailable("Invalid pagination cursor")
            cursor = values[0]
            seen.add(cursor)
        raise RobinhoodUnavailable("Pagination limit exceeded")

    def list_accounts(self):
        return self._pages("/api/v2/crypto/trading/accounts/")

    def balances(self, account_ref):
        if not isinstance(account_ref, str) or not ACCOUNT.fullmatch(account_ref):
            raise ValueError("Invalid account")
        for account in self.list_accounts():
            if account.get("account_number") == account_ref:
                return account
        raise RobinhoodUnavailable("Account not authorized")

    def positions(self, account_ref):
        self.balances(account_ref)
        return self._pages("/api/v2/crypto/trading/holdings/", {"account_number": account_ref})

    def quote(self, symbol):
        if not isinstance(symbol, str) or not PAIR.fullmatch(symbol):
            raise ValueError("Invalid symbol")
        return self._get("/api/v2/crypto/marketdata/best_bid_ask/", {"symbol": symbol})

    def orders(self, account_ref):
        self.balances(account_ref)
        return self._pages("/api/v2/crypto/trading/orders/", {"account_number": account_ref})

    def submit_order(self, account_ref, intent):
        raise RobinhoodUnavailable("Robinhood live orders disabled")

    def cancel_order(self, account_ref, order_ref):
        raise RobinhoodUnavailable("Robinhood live orders disabled")
