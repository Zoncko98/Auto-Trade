"""Conservative exchange-session window observations; NEVER broker executable.

A weekday 09:30-16:00 ET is only a candidate regular-hours window:
holidays, half-days, halts, exchange calendar and broker permissions remain
unverified without an independent session source. Weekend/clock closure is
a deterministic blocker, not an override of a signed broker market check.
"""
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

NEW_YORK=ZoneInfo("America/New_York")

def session_observation(broker, *, now=None):
    now=now or datetime.now(timezone.utc)
    if not isinstance(now,datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("A timezone-aware observation timestamp is required")
    if broker=="paper":
        return {"state":"SIMULATION_NO_BROKER_SESSION",
                "broker_session_verified":False,
                "executable_market_open":False}
    if broker=="robinhood_crypto":
        return {"state":"CRYPTO_VENUE_24H_SCHEDULE_NOT_BROKER_ENTITLEMENT",
                "broker_session_verified":False,
                "executable_market_open":False}
    if broker not in ("schwab","webull"):
        raise ValueError("Unknown broker session")
    local=now.astimezone(NEW_YORK)
    if local.weekday()>=5:
        state="EQUITIES_CLOSED_WEEKEND"
    elif not time(9,30)<=local.time()<time(16,0):
        state="OUTSIDE_US_REGULAR_TRADING_HOURS"
    else:
        state="REGULAR_HOURS_WINDOW_HOLIDAYS_UNVERIFIED"
    return {
        "state":state,
        "exchange_timezone":"America/New_York",
        "regular_hours_reference":"09:30-16:00 ET",
        "broker_session_verified":False,
        "executable_market_open":False,
        "requires_authenticated_broker_hours":True,
    }
