"""Source-faithful Robinhood Crypto v2 execution ESTIMATE diagnostics.

Official API: GET /api/v2/crypto/trading/estimated_price/. This is a
quantity-specific signed *estimate*, not an accepted broker executable limit.
No private identifiers, prices, balances, quantities or fees are persisted.
Crossed books and missing provider timestamps never become authorizations.
"""
from __future__ import annotations
from datetime import datetime,timezone
from decimal import Decimal,InvalidOperation
from .market_sources import _sourced_time,MarketSourceError
from .models import utc

ALLOWLIST={"BTC-USD":Decimal("0.0001"),"ETH-USD":Decimal("0.01")}

def _decimal(raw):
    # The signed HTTP JSON response may use native JSON numeric values.
    # Conversion is permitted ONLY for redacted GET diagnostics; these
    # values are not accepted by the live canonical order engine.
    if isinstance(raw,bool) or not isinstance(raw,(str,int,float,Decimal)):
        raise ValueError("SIGNED_ESTIMATE_DECIMAL_TYPE")
    try:value=Decimal(str(raw))
    except (InvalidOperation,TypeError,ValueError):
        raise ValueError("SIGNED_ESTIMATE_DECIMAL_INVALID") from None
    if not value.is_finite() or value<0 or value.adjusted()>15:
        raise ValueError("SIGNED_ESTIMATE_DECIMAL_INVALID")
    return value

def inspect(payload,symbol,quantity,*,now=None):
    """Pure conservative verifier; allowlisted failure state only."""
    now=utc(now or datetime.now(timezone.utc))
    if symbol not in ALLOWLIST:
        return "SIGNED_ESTIMATE_SYMBOL_NOT_ALLOWLISTED"
    if not isinstance(payload,dict) or not isinstance(payload.get("results"),list):
        return "SIGNED_ESTIMATE_SCHEMA_UNVERIFIED"
    rows=[x for x in payload["results"] if isinstance(x,dict)
          and x.get("symbol")==symbol]
    if len(rows)!=1:
        return "SIGNED_ESTIMATE_IDENTITY_UNVERIFIED"
    row=rows[0]
    try:
        if _decimal(row.get("quantity"))!=quantity:
            return "SIGNED_ESTIMATE_QUANTITY_MISMATCH"
        if row.get("side") not in ("both","bid","ask"):
            return "SIGNED_ESTIMATE_SIDE_UNVERIFIED"
        _sourced_time(row.get("timestamp"),now,ttl=20)
        bid=_decimal(row.get("bid"));ask=_decimal(row.get("ask"))
        fee=_decimal(row.get("fee_ratio"))
        _decimal(row.get("est_fee"))
    except (ValueError,TypeError,MarketSourceError):
        return "SIGNED_ESTIMATE_FIELDS_OR_TIMESTAMP_UNVERIFIED"
    if bid<=0 or ask<=0:
        return "SIGNED_ESTIMATE_BID_ASK_UNVERIFIED"
    if bid>ask:
        return "SIGNED_ESTIMATE_CROSSED"
    if (ask-bid)/ask>Decimal("0.015"):
        return "SIGNED_ESTIMATE_SPREAD_TOO_WIDE"
    if fee>Decimal("0.5"):
        return "SIGNED_ESTIMATE_FEE_OUT_OF_RANGE"
    return "SIGNED_ESTIMATE_FRESH_NONCROSSED_GET_ONLY"

def observed(client,symbol,*,now=None):
    """One authenticated provider GET; no credential or quote data output."""
    if symbol not in ALLOWLIST:return "SIGNED_ESTIMATE_SYMBOL_NOT_ALLOWLISTED"
    if not callable(getattr(client,"estimated_price",None)):
        return "SIGNED_ESTIMATE_CLIENT_UNAVAILABLE"
    try:
        doc=client.estimated_price(symbol,"both",ALLOWLIST[symbol])
    except Exception:
        return "SIGNED_ESTIMATE_BROKER_GET_UNAVAILABLE"
    return inspect(doc,symbol,ALLOWLIST[symbol],now=now)
