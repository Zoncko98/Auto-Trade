"""Independent timing and price agreement for Robinhood v2 top-of-book.

Robinhood's signed v2 best_bid_ask returns bid/ask but not a venue timestamp
or last trade. Do not synthesize those fields. Independently validate a
timestamped public Coinbase trade and bound the duration of the signed GET.
The result is RESEARCH/RISK EVIDENCE, not a permit to place a broker order.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from .models import MarketSnapshot, AssetClass, amount, utc

_ALLOWED = {"BTC-USD": "BTCUSD", "ETH-USD": "ETHUSD"}


class DualQuoteUnavailable(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class DualQuoteEvidence:
    symbol: str
    signed_bid: Decimal
    signed_ask: Decimal
    external_last: Decimal
    signed_request_started_at: datetime
    signed_request_completed_at: datetime
    independent_trade_at: datetime
    examined_at: datetime

    @property
    def public(self):
        return {
            "source": "ROBINHOOD_SIGNED_BID_ASK_PLUS_COINBASE_PUBLIC_LAST",
            "broker_venue_timestamp_provided": False,
            "independent_trade_timestamp_verified": True,
            "broker_request_duration_ms": round(1000 * (
                self.signed_request_completed_at-self.signed_request_started_at).total_seconds()),
            "broker_executable_quote_certified": False,
            "v2_order_authorized": False,
        }


def attest_quote(signed, public_trade: MarketSnapshot, symbol: str,
                 *, request_started_at, request_completed_at, examined_at=None):
    if symbol not in _ALLOWED:
        raise DualQuoteUnavailable("INDEPENDENT_SOURCE_NOT_ALLOWLISTED")
    begin=utc(request_started_at)
    finish=utc(request_completed_at)
    now=utc(examined_at or datetime.now(timezone.utc))
    duration=(finish-begin).total_seconds()
    if duration<0 or duration>3 or (now-finish).total_seconds()>5 or (
            finish-now).total_seconds()>2:
        raise DualQuoteUnavailable("SIGNED_BROKER_HTTP_TIMING_UNVERIFIED")
    if not isinstance(signed,dict) or not isinstance(signed.get("results"),list):
        raise DualQuoteUnavailable("SIGNED_BROKER_BID_ASK_RESPONSE_UNVERIFIED")
    rows=[row for row in signed["results"] if isinstance(row,dict)
          and row.get("symbol")==symbol]
    if len(rows)!=1:
        raise DualQuoteUnavailable("SIGNED_BROKER_SYMBOL_NOT_UNIQUE")
    try:
        bid=amount(rows[0].get("bid"),"signed bid",False)
        ask=amount(rows[0].get("ask"),"signed ask",False)
    except (ValueError,TypeError):
        raise DualQuoteUnavailable("SIGNED_BROKER_BID_ASK_INVALID") from None
    if ask<bid or (ask-bid)/ask>Decimal("0.015"):
        raise DualQuoteUnavailable("SIGNED_BROKER_SPREAD_UNVERIFIED")
    if (not isinstance(public_trade,MarketSnapshot) or
        public_trade.asset_class is not AssetClass.CRYPTO or
        public_trade.symbol!=_ALLOWED[symbol] or
        public_trade.source!="coinbase_public_paper" or
        not public_trade.market_open):
        raise DualQuoteUnavailable("INDEPENDENT_TRADE_SOURCE_UNVERIFIED")
    delta=(now-public_trade.observed_at).total_seconds()
    age_received=(now-public_trade.received_at).total_seconds()
    if not -2<=delta<=20 or not -2<=age_received<=20:
        raise DualQuoteUnavailable("INDEPENDENT_TRADE_TIME_UNVERIFIED")
    last=public_trade.last
    # The public trade is only a cross-check; broker bid/ask define the
    # executable LIMIT-price envelope. Never replace the broker top of book.
    midpoint=(bid+ask)/2
    if abs(last-midpoint)/midpoint>Decimal("0.01"):
        raise DualQuoteUnavailable("BROKER_PUBLIC_PRICE_DIVERGENCE")
    return DualQuoteEvidence(symbol,bid,ask,last,begin,finish,
                             public_trade.observed_at,now)
