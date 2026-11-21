"""Verified rolling V2 crypto-paper activity: scan evidence vs actual simulated fills.

Read-only SQLite snapshots; no broker access, no credential lookups, no orders.
A recorded strategy signal is NOT a fill, and historical synthetic equity P/L
is NOT automatically attributed to the requested rolling time window.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import json
import re
import sqlite3
import stat

from .models import utc

SYMBOLS = {"BTCUSD": "v2-paper-btcusd", "ETHUSD": "v2-paper-ethusd"}
SCAN_DB = "paper_scan_history.sqlite3"
FILL_DB = "sim.sqlite3"
AI_STATES = ("PASS", "VETO", "UNAVAILABLE", "NOT_CONFIGURED", "NOT_INVOKED")
FEE_STATES = ("EXIT_NOT_GATED","INSUFFICIENT_HISTORY","EVIDENCE_UNAVAILABLE",
              "SHADOW_PASS_PAST_RESISTANCE_ROOM","SHADOW_REJECT_REWARD_AFTER_FEES",
              "SHADOW_REJECT_SPREAD")
_BLOCKER = re.compile(r"^[A-Z][A-Z0-9_]{0,79}$")
MAX_DB_BYTES = 32_000_000


def _private_readonly(base, filename):
    path = Path(base) / filename
    try:
        st = path.lstat()
        if (not stat.S_ISREG(st.st_mode) or st.st_mode & 0o077 or
                not 0 < st.st_size <= MAX_DB_BYTES):
            return None
        return sqlite3.connect("file:" + str(path) + "?mode=ro",
                               uri=True, timeout=2)
    except (OSError, ValueError):
        return None


def _stamp(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 45:
        raise ValueError("INVALID_LEDGER_TIMESTAMP")
    try:
        at = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return utc(at)
    except (ValueError, TypeError, OverflowError):
        raise ValueError("INVALID_LEDGER_TIMESTAMP") from None


def _decimal(value):
    if isinstance(value, bool) or value is None:
        raise ValueError("INVALID_LEDGER_FEE")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("INVALID_LEDGER_FEE") from None
    if not amount.is_finite() or not 0 <= amount <= 1_000_000:
        raise ValueError("INVALID_LEDGER_FEE")
    return amount


def read_activity(directory, *, hours=3, now=None):
    if hours not in (3, 24):
        raise ValueError("INVALID_PAPER_ACTIVITY_WINDOW")
    now = utc(now or datetime.now(timezone.utc))
    start = now - timedelta(hours=hours)
    since = int(start.timestamp())
    until = int(now.timestamp())
    result = {sym: {
        "symbol": sym, "window_hours": hours,
        "scans_state": "NOT_RECORDED",
        "scan_minutes": 0, "signal_minutes": 0,
        "entry_blocked_minutes": 0, "exit_blocked_minutes": 0,
        "no_signal_minutes": 0, "data_error_minutes": 0,
        "rejection_reasons": {},
        "ai_shadow": {ai: 0 for ai in AI_STATES},
        "fee_shadow": {state:0 for state in FEE_STATES},
        "fee_shadow_observations": 0,
        "fee_shadow_coverage": "NOT_RECORDED",
        "simulated_fills": None,
        "simulated_buys": None,
        "simulated_sells": None,
        "simulated_fee_usd": None,
        "fills_state": "FILL_LEDGER_UNAVAILABLE",
        "last_confirmed_simulated_fill_at": None,
        "window_equity_change_usd": None,
        "live_orders_authorized": False,
    } for sym in SYMBOLS}

    db = _private_readonly(directory, SCAN_DB)
    if db is not None:
        try:
            columns={r[1] for r in db.execute("PRAGMA table_info(paper_scans)")}
            fee_expr="fee_shadow_state" if "fee_shadow_state" in columns else "NULL"
            rows = db.execute(
                """SELECT symbol, minute, state, reason, signal, ai_state, equity, """
                +fee_expr+""" FROM paper_scans
                     WHERE minute>=? AND minute<=?
                     ORDER BY symbol, minute LIMIT 10000""",
                (since, until)).fetchall()
            for sym, minute, state, reason, side, ai, equity, fee_state in rows:
                card = result.get(sym)
                if card is None:
                    continue
                card["scans_state"] = "OBSERVED"
                card["scan_minutes"] += 1
                if side in ("BUY", "SELL"):
                    card["signal_minutes"] += 1
                # PaperPipeline returns code="BLOCKED" and the candidate's
                # signal side separately. Keep the canonical ENTRY/EXIT aliases
                # too for historical compatibility with prior scan recordings.
                is_blocked = state in ("BLOCKED", "ENTRY_BLOCKED", "EXIT_BLOCKED")
                if state == "ENTRY_BLOCKED" or (state == "BLOCKED" and side == "BUY"):
                    card["entry_blocked_minutes"] += 1
                if state == "EXIT_BLOCKED" or (state == "BLOCKED" and side == "SELL"):
                    card["exit_blocked_minutes"] += 1
                if state == "NO_SIGNAL":
                    card["no_signal_minutes"] += 1
                if state in ("DATA_UNAVAILABLE", "GAPPED_BARS", "STALE_CANDLES"):
                    card["data_error_minutes"] += 1
                if ai in card["ai_shadow"]:
                    card["ai_shadow"][ai] += 1
                if fee_state in card["fee_shadow"]:
                    card["fee_shadow"][fee_state] += 1
                    card["fee_shadow_observations"] += 1
                    card["fee_shadow_coverage"] = "OBSERVED_ADVISORY_ONLY"
                if is_blocked:
                    code = reason if isinstance(reason, str) and _BLOCKER.fullmatch(reason) else "UNVERIFIED_REJECTION_REASON"
                    card["rejection_reasons"][code] = card["rejection_reasons"].get(code, 0) + 1
                if equity is not None:
                    mark = _decimal(equity)
                    if "_first_equity" not in card:
                        card["_first_equity"] = mark
                    card["_last_equity"] = mark
        except (sqlite3.Error, ValueError, TypeError):
            for card in result.values():
                card["scans_state"] = "SCAN_JOURNAL_UNVERIFIED"
                for key in ("scan_minutes", "signal_minutes", "entry_blocked_minutes",
                            "exit_blocked_minutes", "no_signal_minutes", "data_error_minutes"):
                    card[key] = 0
                card["rejection_reasons"] = {}
                card["ai_shadow"] = {ai: 0 for ai in AI_STATES}
                card["fee_shadow"] = {state: 0 for state in FEE_STATES}
                card["fee_shadow_observations"] = 0
                card["fee_shadow_coverage"] = "SCAN_JOURNAL_UNVERIFIED"
        finally:
            db.close()

    for card in result.values():
        if "_first_equity" in card and "_last_equity" in card:
            card["window_equity_change_usd"] = str(
                (card["_last_equity"] - card["_first_equity"]).quantize(Decimal("0.01")))
        card.pop("_first_equity", None)
        card.pop("_last_equity", None)

    db = _private_readonly(directory, FILL_DB)
    if db is not None:
        try:
            rows = db.execute(
                """SELECT account_id, intent_document, fee, created_at
                   FROM sim_orders
                   WHERE account_id IN (?,?)
                   ORDER BY created_at ASC LIMIT 10001""",
                tuple(SYMBOLS.values())).fetchall()
            if len(rows) > 10000:
                raise ValueError("FILL_JOURNAL_TOO_LARGE")
            # Verify all rows before publishing ANY counts. A malformed historical
            # row is not evidence that the last three hours had zero fills.
            verified = []
            for account, document, fee, at in rows:
                when = _stamp(at)
                intent = json.loads(document)
                if (not isinstance(intent, dict) or intent.get("side") not in ("BUY", "SELL")
                        or account not in SYMBOLS.values()):
                    raise ValueError("INVALID_SIMULATED_INTENT")
                verified.append((account, when, intent["side"], _decimal(fee)))
            for card in result.values():
                card["simulated_fills"] = 0
                card["simulated_buys"] = 0
                card["simulated_sells"] = 0
                card["simulated_fee_usd"] = "0.00"
                card["fills_state"] = "SIMULATED_LEDGER_VERIFIED"
            fees = {sym: Decimal("0") for sym in SYMBOLS}
            for account, when, side, fee in verified:
                if not start <= when <= now:
                    continue
                sym = next(s for s, a in SYMBOLS.items() if a == account)
                card = result[sym]
                card["simulated_fills"] += 1
                card["simulated_buys" if side == "BUY" else "simulated_sells"] += 1
                fees[sym] += fee
                card["last_confirmed_simulated_fill_at"] = when.isoformat()
            for sym, amount in fees.items():
                result[sym]["simulated_fee_usd"] = str(amount.quantize(Decimal("0.01")))
        except (sqlite3.Error, ValueError, TypeError, json.JSONDecodeError):
            for card in result.values():
                card["fills_state"] = "FILL_LEDGER_UNVERIFIED"
                for field in ("simulated_fills", "simulated_buys", "simulated_sells", "simulated_fee_usd"):
                    card[field] = None
                card["last_confirmed_simulated_fill_at"] = None
        finally:
            db.close()
    return result
