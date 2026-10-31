"""Fail-closed capital and order-journal controls for Schwab live trading.

This module has no broker I/O. Broker data must be independently reconciled
before an order is prepared; tests use synthetic values, never credentials.
"""
from __future__ import annotations

import json
import math
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from pathlib import Path

CAPITAL = Decimal("100.00")
MAX_POSITION = Decimal("25.00")
DAILY_LOSS = Decimal("5.00")
SYMBOL_PATTERN = re.compile(r"^[A-Z][A-Z0-9.]{0,9}$")
TERMINAL = {"FILLED", "CANCELED", "REJECTED", "EXPIRED", "REPLACED"}
OPEN_STATUSES = {"AWAITING_PARENT_ORDER", "AWAITING_CONDITION", "AWAITING_STOP_CONDITION",
                 "AWAITING_MANUAL_REVIEW", "ACCEPTED", "AWAITING_UR_OUT",
                 "PENDING_ACTIVATION", "QUEUED", "WORKING", "PENDING_CANCEL",
                 "PENDING_REPLACE", "PARTIAL_FILL", "PENDING_ACKNOWLEDGEMENT",
                 "NEW", "AWAITING_RELEASE_TIME", "PENDING_RECALL"}

class LiveBlocked(RuntimeError):
    """No order is permitted until this fail-closed condition is resolved."""


def money(value, label="amount"):
    if isinstance(value, bool) or value is None:
        raise LiveBlocked(f"Missing or invalid {label}")
    try:
        result = Decimal(str(value))
    except Exception:
        raise LiveBlocked(f"Invalid {label}") from None
    if not result.is_finite():
        raise LiveBlocked(f"Non-finite {label}")
    return result


def position_snapshot(account: dict) -> tuple[dict[str, int], Decimal]:
    sec = account.get("securitiesAccount")
    if not isinstance(sec, dict):
        raise LiveBlocked("A verified Schwab securities account is required")
    # Account registration is not a financing instruction. Margin-enabled accounts
    # may trade cash-only; verified_cash() separately forbids margin debt.
    positions = {}
    market_value = Decimal("0")
    for pos in sec.get("positions", []):
        instrument = pos.get("instrument") or {}
        asset_type=instrument.get("assetType")
        symbol=instrument.get("symbol")
        # Schwab categorizes the user-owned SPYD ETF as COLLECTIVE_INVESTMENT.
        # This exception is explicitly scoped: never treat an arbitrary fund
        # or mutual-fund instrument as an orderable ETF.
        if asset_type!="EQUITY" and not (
            asset_type=="COLLECTIVE_INVESTMENT" and symbol=="SPYD"
        ):
            raise LiveBlocked("Unrecognized broker position type")
        symbol = instrument.get("symbol")
        if not isinstance(symbol, str) or not SYMBOL_PATTERN.fullmatch(symbol):
            raise LiveBlocked("Unexpected broker position symbol")
        qty = money(pos.get("longQuantity"), "broker long quantity")
        short_qty = money(pos.get("shortQuantity", 0), "broker short quantity")
        if short_qty or qty < 0 or qty != qty.to_integral_value():
            raise LiveBlocked("Fractional or short brokerage position")
        if int(qty):
            positions[symbol] = positions.get(symbol, 0) + int(qty)
        market_value += money(pos.get("marketValue"), "position market value")
    if market_value < 0:
        raise LiveBlocked("Negative market value")
    return positions, market_value


def verified_cash(account: dict) -> Decimal:
    """Cash-backed purchasing capacity, never Schwab margin buying power.

    An account may be MARGIN-enabled without using any loan. The live BUY
    limit must be covered by existing positive cash after unsettled funds
    and pending deposits, with no existing margin loan or margin call.
    """
    sec = account.get("securitiesAccount")
    if not isinstance(sec, dict):
        raise LiveBlocked("Missing Schwab securities account")
    account_type = sec.get("type")
    if account_type not in {"CASH", "MARGIN", "CASH_IRA", "MARGIN_IRA"}:
        raise LiveBlocked("Unsupported Schwab account type")
    if sec.get("isClosingOnlyRestricted") is True:
        raise LiveBlocked("Schwab account is restricted to closing orders")
    balances = sec.get("currentBalances")
    if not isinstance(balances, dict):
        raise LiveBlocked("Broker current balances unavailable")

    cash = money(balances.get("cashBalance", balances.get("totalCash")), "cash balance")
    # Margin-account balance responses often omit unsettledCash entirely.
    # The order journal separately enforces a T+1 trading pause after sells.
    unsettled = money(balances.get("unsettledCash", 0), "unsettled cash")
    deposits = money(balances.get("pendingDeposits", 0), "pending deposits")
    if cash < 0 or unsettled < 0 or deposits < 0:
        raise LiveBlocked("Negative or inconsistent cash fields")

    if account_type in {"MARGIN", "MARGIN_IRA"}:
        # Do not take 'buyingPower', 'stockBuyingPower', 'dayTradingBuyingPower'
        # or SMA as cash. Require evidence that no margin debt is outstanding.
        margin_debt = money(balances.get("marginBalance"), "margin balance")
        if margin_debt != 0:
            raise LiveBlocked("Margin loan already outstanding; cash-only bot halted")
        if balances.get("isInCall") is True:
            raise LiveBlocked("Account is in a margin call")
        for field in ("shortBalance", "shortMarketValue", "shortOptionMarketValue",
                      "cashDebitCallValue", "maintenanceCall", "regTCall"):
            if field in balances and money(balances[field], field) != 0:
                raise LiveBlocked("Margin, short or call exposure is nonzero")
    # In a margin-enabled account these fields might exceed actual cash.
    # They are never used alone and can only reduce our conservative budget.
    spendable = cash - unsettled - deposits
    for field in ("cashAvailableForTrading", "cashAvailableForWithdrawal",
                  "availableFundsNonMarginableTrade"):
        if field in balances and balances[field] is not None:
            amount = money(balances[field], field)
            if amount < 0:
                raise LiveBlocked("Negative broker cash-availability field")
            spendable = min(spendable, amount)
    return max(Decimal("0"), spendable)


def equity_value(account: dict) -> Decimal:
    sec = account.get("securitiesAccount", {})
    balances = sec.get("currentBalances") or {}
    if balances.get("liquidationValue") is not None:
        return money(balances["liquidationValue"], "liquidation value")
    _, market_value = position_snapshot(account)
    return money(balances.get("totalCash"), "total cash") + market_value


def quote_levels(data: dict, now: datetime) -> tuple[Decimal, Decimal]:
    block = data.get("quote") if isinstance(data, dict) else None
    if not isinstance(block, dict):
        raise LiveBlocked("Missing Schwab quote")
    bid, ask = money(block.get("bidPrice"), "bid"), money(block.get("askPrice"), "ask")
    millis = money(block.get("quoteTime"), "quote time")
    age = Decimal(str(now.timestamp())) - millis / 1000
    if bid < 5 or ask < 5 or bid > ask or (ask - bid) / ask > Decimal("0.02"):
        raise LiveBlocked("Invalid or excessive bid/ask spread")
    if age < -5 or age > 60:
        raise LiveBlocked("Quote is stale or timestamp is invalid")
    return bid, ask


def cross_signal(candles: list[dict], now: datetime) -> tuple[str, int]:
    """Return crossover on completed five-minute candles only."""
    if len(candles) < 6:
        raise LiveBlocked("Insufficient candle history")
    rows = sorted(candles, key=lambda x: x["datetime"])
    clean = []
    cutoff_ms = int(now.timestamp() * 1000) - 60000
    for row in rows:
        t = int(row["datetime"])
        close = money(row.get("close"), "candle close")
        # Candle timestamps are OPEN times. Only use fully completed candles.
        if 0 < t + 300000 <= cutoff_ms and close > 0:
            clean.append((t, close))
    if len(clean) < 6 or clean[-1][0] + 300000 < int(now.timestamp()*1000)-12*60000:
        raise LiveBlocked("Market candles missing or stale")
    if len(set(t for t, _ in clean)) != len(clean):
        raise LiveBlocked("Duplicate candle timestamps")
    p = [v for _,v in clean[-6:]]
    short_prev=sum(p[-4:-1])/3
    long_prev=sum(p[-6:-1])/5
    short_now=sum(p[-3:])/3
    long_now=sum(p[-5:])/5
    if short_prev <= long_prev and short_now > long_now:
        return "BUY", clean[-1][0]
    if short_prev >= long_prev and short_now < long_now:
        return "SELL", clean[-1][0]
    return "HOLD", clean[-1][0]


def buy_quantity(ask: Decimal, available_cash: Decimal, total_exposure: Decimal) -> tuple[int, Decimal]:
    # Marketable day-only limit: at most 0.5% above verified ask.
    limit = (ask * Decimal("1.005")).quantize(Decimal("0.01"), rounding=ROUND_UP)
    budget = min(MAX_POSITION, CAPITAL - total_exposure, available_cash)
    if budget <= 0 or limit <= 0:
        return 0, limit
    qty = int((budget / limit).to_integral_value(rounding=ROUND_DOWN))
    return max(0, qty), limit


def sell_limit(bid: Decimal) -> Decimal:
    return (bid * Decimal("0.995")).quantize(Decimal("0.01"), rounding=ROUND_DOWN)


@dataclass
class OrderLedger:
    path: Path
    data: dict

    @classmethod
    def open(cls, path):
        path=Path(path)
        if path.exists():
            if path.stat().st_mode & 0o077:
                raise LiveBlocked("Live journal permissions must be owner-only")
            doc=json.loads(path.read_text(encoding="utf-8"))
            if doc.get("version") != 1 or not isinstance(doc.get("orders"), list):
                raise LiveBlocked("Invalid journal schema")
        else:
            doc={"version": 1,"orders": [],"day": "", "day_start_equity": None,
                 "last_candle": 0, "halted": False}
        return cls(path, doc)

    def save(self):
        self.path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        payload=json.dumps(self.data, sort_keys=True, allow_nan=False).encode()
        fd,tmp=tempfile.mkstemp(prefix=".journal-",dir=self.path.parent)
        try:
            os.fchmod(fd,0o600)
            with os.fdopen(fd,"wb") as out:
                out.write(payload)
                out.flush()
                os.fsync(out.fileno())
            os.replace(tmp,self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def ready(self):
        if self.data.get("halted"):
            raise LiveBlocked("Live journal has a persistent HALT")
        if any(order.get("state") not in TERMINAL
               for order in self.data["orders"]):
            raise LiveBlocked("Unresolved order exists; no automatic retries")

    def record_before_network(self, symbol, action, quantity, limit_price, candle, reason=""):
        self.ready()
        if self.data.get("last_candle",0) >= candle:
            raise LiveBlocked("This candle has already been used for a trade")
        if action not in ("BUY","SELL") or not SYMBOL_PATTERN.fullmatch(symbol):
            raise LiveBlocked("Invalid trade intent")
        if not isinstance(quantity,int) or not 1 <= quantity <= 100:
            raise LiveBlocked("Invalid whole-share quantity")
        p=money(limit_price,"limit price")
        if p <= 0 or (action == "BUY" and p*quantity > CAPITAL):
            raise LiveBlocked("Buy exceeds $100 hard cap")
        self.data["last_candle"]=candle
        entry={"symbol":symbol,"action":action,"quantity":quantity,
               "limit_price":str(p),"candle":candle,"state":"SUBMITTING",
               "created_at":datetime.now(timezone.utc).isoformat(),"order_id":None,
               "reason":str(reason)[:500]}
        self.data["orders"].append(entry)
        self.save()   # fsync before any broker POST: crashes never trigger a retry.
        return entry

    def mark_accepted(self, entry, order_id):
        if entry.get("state")!="SUBMITTING" or not str(order_id).isdigit():
            raise LiveBlocked("Missing or invalid broker order ID")
        entry["state"]="ACCEPTED"
        entry["order_id"]=str(order_id)
        self.save()

    def mark_terminal(self, entry, broker_state):
        if broker_state not in TERMINAL:
            raise LiveBlocked("Broker order not definitively terminal")
        if entry.get("state")!="ACCEPTED" or not entry.get("order_id"):
            raise LiveBlocked("Unreconciled order cannot be marked terminal")
        entry["state"]=broker_state
        self.save()

    def halt(self, reason="order reconciliation required"):
        self.data["halted"]=True
        self.data["halt_reason"]=reason[:120]
        self.save()
