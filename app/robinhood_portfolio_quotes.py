"""Read-only indicative valuation for USDC when Robinhood v2 has no mark.

Used ONLY by the Robinhood holdings portfolio display, never in order sizing,
signal selection, eligibility, reconciliation or risk enforcement.
"""
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from threading import Lock
import json
import time
import urllib.request

USDC_PRICE_URL = (
    "https://api.coingecko.com/api/v3/simple/price?"
    "ids=usd-coin&vs_currencies=usd&include_last_updated_at=true"
)
_CACHE = {"until": 0.0, "quote": None}
_LOCK = Lock()

def _parse_usdc_response(body, now):
    """Fail closed on stale or malformed external marks."""
    if isinstance(body,bytes):
        if len(body)>4096:
            return None
        body=body.decode("utf-8")
    if not isinstance(body,str) or len(body)>4096:
        return None
    try:
        payload=json.loads(body)
        record=payload["usd-coin"]
        stamp=record["last_updated_at"]
        if type(stamp) is not int or not 0<=now-stamp<=300:
            return None
        price=Decimal(str(record["usd"]))
        if not price.is_finite() or not Decimal("0")<price<=Decimal("10"):
            return None
        return {"price":price,"source":"CoinGecko USDC/USD indicative",
                "as_of":datetime.fromtimestamp(stamp,timezone.utc).isoformat()}
    except (ValueError,TypeError,KeyError,OverflowError,InvalidOperation,UnicodeError):
        return None

def get_display_only_mark(symbol, *, fetch=None, now=None):
    """Return a fresh externally identified quote only for canonical USDC-USD.

    Do not guess that the stablecoin is always worth $1. Never fall back to
    similarly named assets, stale values, or a trading-execution quote.
    """
    if symbol!="USDC-USD":
        return None
    current=time.time() if now is None else float(now)
    if fetch is None:
        with _LOCK:
            if current<_CACHE["until"]:
                return _CACHE["quote"]
        def request():
            req=urllib.request.Request(USDC_PRICE_URL,headers={
                "Accept":"application/json","User-Agent":"AutoTraderPortfolio/1.0"})
            with urllib.request.urlopen(req,timeout=5) as reply:
                if getattr(reply,"status",200)!=200:return b""
                return reply.read(4097)
        fetch=request
        use_cache=True
    else:
        use_cache=False
    try:
        mark=_parse_usdc_response(fetch(),current)
    except (OSError,TimeoutError,ValueError,TypeError,UnicodeError):
        mark=None
    if use_cache:
        with _LOCK:
            _CACHE["until"]=current+(45 if mark else 15)
            _CACHE["quote"]=mark
    return mark
