"""Strict public Coinbase Exchange observations for broker-free V2 paper crypto.

Only fixed, allowlisted product paths on the Coinbase public HTTPS endpoint.
Never uses credentials and never claims these quotes are Robinhood/Webull
executable. Closed candles are subsequently formed from real ticker samples,
not a synthesized historical backfill.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.request import Request, urlopen
import json
from .models import AssetClass, MarketSnapshot, utc

PRODUCTS = {"BTCUSD":"BTC-USD", "ETHUSD":"ETH-USD"}
BASE = "https://api.exchange.coinbase.com/products/"
SOURCE = "coinbase_public_paper"


class PublicFeedError(ValueError):
    pass


def normalize_ticker(document, symbol, *, now=None):
    if symbol not in PRODUCTS or not isinstance(document,dict):
        raise PublicFeedError("PUBLIC_MARKET_SCHEMA_INVALID")
    if set(("time","bid","ask","price"))-set(document):
        raise PublicFeedError("PUBLIC_MARKET_FIELDS_MISSING")
    now=utc(now or datetime.now(timezone.utc))
    raw=document["time"]
    if not isinstance(raw,str) or len(raw)>45 or not raw.endswith("Z"):
        raise PublicFeedError("PUBLIC_MARKET_TIME_INVALID")
    try:
        observed=utc(datetime.fromisoformat(raw.replace("Z","+00:00")))
        bid,ask,last=(Decimal(str(document[x])) for x in ("bid","ask","price"))
    except (ValueError,TypeError,InvalidOperation) as exc:
        raise PublicFeedError("PUBLIC_MARKET_FIELDS_INVALID") from exc
    if any(not n.is_finite() or n<=0 or n.adjusted()>14 or n.as_tuple().exponent < -12
           for n in (bid,ask,last)):
        raise PublicFeedError("PUBLIC_MARKET_PRICE_INVALID")
    if ask<bid:
        raise PublicFeedError("PUBLIC_MARKET_CROSSED")
    age=(now-observed).total_seconds()
    if age < -2 or age>90:
        raise PublicFeedError("PUBLIC_MARKET_STALE_OR_FUTURE")
    # Paper-only: crypto Coinbase Exchange continuously trades; this flag
    # is NEVER evidence of the user's broker being open or executable.
    return MarketSnapshot(symbol,AssetClass.CRYPTO,SOURCE,observed,now,
                          bid,ask,last,True)


def fetch_ticker(symbol, *, now=None, opener=urlopen):
    product=PRODUCTS.get(symbol)
    if product is None:raise PublicFeedError("UNSUPPORTED_PUBLIC_MARKET")
    req=Request(BASE+product+"/ticker",headers={
        "User-Agent":"AutoTrader-V2-Paper/1.0",
        "Accept":"application/json","Cache-Control":"no-cache"},method="GET")
    try:
        with opener(req,timeout=8) as response:
            if response.status!=200:
                raise PublicFeedError("PUBLIC_MARKET_HTTP_ERROR")
            raw=response.read(16_385)
        if len(raw)>16_384:raise PublicFeedError("PUBLIC_MARKET_RESPONSE_OVERSIZE")
        data=json.loads(raw)
    except PublicFeedError:
        raise
    except Exception as exc:
        raise PublicFeedError("PUBLIC_MARKET_UNAVAILABLE") from exc
    return normalize_ticker(data,symbol,now=now)
