"""Deterministic PAPER-ONLY trading simulator. No brokerage or network access."""
from __future__ import annotations

import csv
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

from ai_review import ReviewDecision
from dashboard_control import DEFAULT_SETTINGS, validated_settings
from risk_controls import RiskControls, RiskLimits


def parse_utc(value: str) -> datetime:
    when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if when.tzinfo is None:
        raise ValueError("Quote timestamp must include a timezone")
    return when.astimezone(timezone.utc)


class PaperEngine:
    """Consume dated price observations; fill simulated orders at input prices.

    These are illustrative fills with zero slippage, commissions and fees;
    they are NOT executable orders, market data, or verified returns.
    """

    def __init__(self, state_path: Path, limits: RiskLimits,
                 short_window: int = 3, long_window: int = 5,
                 allowed_symbols: set[str] | None = None,
                 allow_fractional: bool = True,
                 max_quote_age_seconds: int = 600,
                 reviewer=None):
        if not 1 < short_window < long_window:
            raise ValueError("Expected 1 < short_window < long_window")
        self.path = Path(state_path)
        self.risk = RiskControls(limits)
        self.short_window, self.long_window = short_window, long_window
        self.allowed_symbols = allowed_symbols or {"SPY"}
        self.allow_fractional = allow_fractional
        self.max_quote_age_seconds = max_quote_age_seconds
        self.reviewer = reviewer  # No reviewer means deny all new entries.
        self.trade_settings = validated_settings(DEFAULT_SETTINGS.copy())
        if self.path.exists():
            self.state = json.loads(self.path.read_text())
            if self.state.get("schema") != 1:
                raise ValueError("Unsupported state schema")
        else:
            self.state = dict(schema=1, cash=limits.initial_capital,
                              positions={}, history={}, last_processed={},
                              day=None, day_start_equity=limits.initial_capital,
                              trades=[], reviews=[], halted=False, reserved_profit=0.0,
                              daily_target_reached=False)

    def set_trade_settings(self, settings: dict) -> None:
        new = validated_settings(settings)
        self.trade_settings = new
        self.risk = RiskControls(RiskLimits(
            initial_capital=self.risk.limits.initial_capital,
            max_position_pct=new["max_position_pct"],
            max_daily_loss=new["max_daily_loss"],
            max_open_positions=new["max_open_positions"],
        ))

    def equity(self) -> float:
        total = float(self.state["cash"]) + float(self.state.get("reserved_profit", 0.0))
        for symbol, pos in self.state["positions"].items():
            history = self.state["history"].get(symbol, [])
            if not history:
                raise ValueError("Missing last price for held position")
            total += pos["quantity"] * history[-1]["price"]
        return total

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w") as file:
            json.dump(self.state, file, indent=2, allow_nan=False)
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp, self.path)

    def process(self, symbol: str, price: float, timestamp: str,
                now: datetime | None = None) -> str:
        symbol = symbol.strip().upper()
        if symbol not in self.allowed_symbols:
            return "SKIP: symbol not permitted"
        if not math.isfinite(price) or price <= 0:
            return "SKIP: invalid price"
        when = parse_utc(timestamp)
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        age = (now - when).total_seconds()
        if age < -30 or age > self.max_quote_age_seconds:
            return "SKIP: stale or future price"
        previous = self.state["last_processed"].get(symbol)
        if previous and when <= parse_utc(previous):
            return "SKIP: duplicate or out-of-order quote"

        date = when.date().isoformat()
        if self.state["day"] != date:
            self.state["day"] = date
            self.state["day_start_equity"] = self.equity()
            self.state["halted"] = False
            self.state["daily_target_reached"] = False

        history = self.state["history"].setdefault(symbol, [])
        history.append({"timestamp": when.isoformat(), "price": price})
        if len(history) > self.long_window + 1:
            del history[:-(self.long_window + 1)]
        self.state["last_processed"][symbol] = when.isoformat()
        equity = self.equity()
        if self.state["day_start_equity"] - equity >= self.risk.limits.max_daily_loss:
            self.state["halted"] = True
        target_pct = self.trade_settings["daily_growth_target_pct"]
        if target_pct > 0 and equity >= self.state["day_start_equity"] * (1 + target_pct / 100):
            self.state["daily_target_reached"] = True

        signal = "HOLD"
        if len(history) >= self.long_window + 1:
            prices = [x["price"] for x in history]
            previous_short = sum(prices[-self.short_window-1:-1]) / self.short_window
            previous_long = sum(prices[-self.long_window-1:-1]) / self.long_window
            current_short = sum(prices[-self.short_window:]) / self.short_window
            current_long = sum(prices[-self.long_window:]) / self.long_window
            crossover_up = previous_short <= previous_long and current_short > current_long
            crossover_down = previous_short >= previous_long and current_short < current_long
            if crossover_down and symbol in self.state["positions"]:
                pos = self.state["positions"].pop(symbol)
                proceeds = round(pos["quantity"] * price, 2)
                basis = round(pos["quantity"] * pos["entry_price"], 2)
                profit = round(proceeds - basis, 2)
                self.state["cash"] = round(self.state["cash"] + proceeds, 2)
                reserved = 0.0
                if profit > 0:
                    reserved = min(self.state["cash"], round(
                        profit * (100 - self.trade_settings["reinvest_pct"]) / 100, 2))
                    self.state["cash"] = round(self.state["cash"] - reserved, 2)
                    self.state["reserved_profit"] = round(
                        self.state.get("reserved_profit", 0.0) + reserved, 2)
                self.state["trades"].append(dict(action="PAPER_SELL", symbol=symbol,
                    price=price, quantity=pos["quantity"], timestamp=when.isoformat(),
                    realized_pnl=profit, reserved_profit=reserved,
                    reinvest_pct=self.trade_settings["reinvest_pct"],
                    reason="Short moving average crossed below long moving average; "
                           "simulated position exit",
                    settings=self.trade_settings.copy()))
                signal = "PAPER_SELL"
            elif (crossover_up and symbol not in self.state["positions"]
                  and not self.state["halted"] and not self.state.get("daily_target_reached", False)):
                budget = min(self.state["cash"] * self.trade_settings["allocation_pct"] / 100,
                             equity * self.risk.limits.max_position_pct / 100)
                if self.trade_settings["max_order_usd"] > 0:
                    budget = min(budget, self.trade_settings["max_order_usd"])
                # Round down to cents and fractional units, never above the budget.
                budget = math.floor(max(0, budget) * 100) / 100
                quantity = (math.floor(budget / price * 1_000_000) / 1_000_000
                            if self.allow_fractional else int(budget / price))
                cost = round(quantity * price, 2)
                day_pnl = equity - self.state["day_start_equity"]
                allowed, _ = self.risk.check_new_position(
                    cost, self.state["cash"], equity,
                    len(self.state["positions"]), day_pnl)
                if quantity > 0 and allowed:
                    candidate = {
                        "trade_type": "PAPER_BUY",
                        "signal": "moving_average_cross_up",
                        "symbol": symbol,
                        "timestamp_utc": when.isoformat(),
                        "price": price,
                        "quantity": quantity,
                        "notional_usd": cost,
                        "available_cash_usd": round(self.state["cash"], 2),
                        "equity_usd": round(equity, 2),
                        "current_day_pnl_usd": round(day_pnl, 2),
                        "open_positions": len(self.state["positions"]),
                        "max_position_pct": self.risk.limits.max_position_pct,
                        "max_daily_loss_usd": self.risk.limits.max_daily_loss,
                        "allocation_pct": self.trade_settings["allocation_pct"],
                        "reinvest_pct": self.trade_settings["reinvest_pct"],
                        "max_order_usd": self.trade_settings["max_order_usd"],
                        "short_ma": round(current_short, 6),
                        "long_ma": round(current_long, 6),
                        "last_prices": prices,
                    }
                    try:
                        decision = (self.reviewer.review(candidate) if self.reviewer
                                    else ReviewDecision(False, "AI reviewer unavailable", "unconfigured"))
                        if not isinstance(decision, ReviewDecision):
                            raise TypeError("Invalid AI review result")
                    except Exception:
                        decision = ReviewDecision(False, "AI reviewer raised an error", "error")
                    review_event = {
                        "timestamp": when.isoformat(), "symbol": symbol,
                        "action": "PAPER_BUY", "quantity": quantity,
                        "price": price, "approved": decision.approved,
                        "model": decision.model, "reason": decision.reason,
                        "providers": list(decision.provider_details),
                        "estimated_ai_cost_usd": decision.estimated_cost_usd,
                        "strategy_reason": "3-period MA crossed above 5-period MA",
                        "risk_flags": list(decision.risk_flags),
                    }
                    self.state.setdefault("reviews", []).append(review_event)
                    # Keep full paper-trading audit history for the web dashboard.
                    if decision.approved:
                        # Risk controls already passed; the model cannot change the order.
                        self.state["cash"] = round(self.state["cash"] - cost, 2)
                        self.state["positions"][symbol] = dict(quantity=quantity, entry_price=price)
                        self.state["trades"].append(dict(action="PAPER_BUY", symbol=symbol,
                            price=price, quantity=quantity, timestamp=when.isoformat(),
                            reason="Short moving average crossed above long moving average; "
                                   "risk controls passed and AI approved paper entry",
                            settings=self.trade_settings.copy(),
                            ai_review=review_event))
                        signal = "PAPER_BUY"
                    else:
                        signal = "AI_REJECTED"
        self.save()
        return signal

    def ingest_csv(self, csv_path: Path, now: datetime | None = None) -> list[str]:
        if not csv_path.exists():
            return []
        results = []
        with csv_path.open(newline="") as f:
            reader = csv.DictReader(f)
            if not {"timestamp", "symbol", "price"}.issubset(reader.fieldnames or []):
                raise ValueError("CSV must contain timestamp,symbol,price columns")
            for row in reader:
                results.append(self.process(row["symbol"], float(row["price"]),
                                            row["timestamp"], now=now))
        return results
