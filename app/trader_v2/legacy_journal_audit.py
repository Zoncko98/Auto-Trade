"""V2 read-only legacy broker order journal evidence; never calls a broker.

Legacy orders remain owned by the existing V1 workers. This module does not
write/initialize any journal, import broker SDKs, or authorize V2 execution.
Local terminal records are NOT proof of signed broker acceptance/reconciliation.
"""
from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
import json
import os
import sqlite3
import stat

from .readonly_adapters import private_json

MAX_RECORDS = 5000
WEBULL_TERMINAL = frozenset({"FILLED", "CANCELLED", "FAILED"})
ROBINHOOD_TERMINAL = frozenset({
    "filled", "canceled", "cancelled", "failed", "rejected",
    "expired", "externally_reconciled",
})
VALID_WEBULL = WEBULL_TERMINAL | frozenset({
    "INTENT_UNCONFIRMED", "SUBMITTED_UNCONFIRMED", "PENDING",
    "SUBMITTED", "PARTIAL_FILLED", "PARTIAL_TERMINAL",
})
VALID_ROBINHOOD = ROBINHOOD_TERMINAL | frozenset({
    "intent_unconfirmed", "submitted_unconfirmed", "open", "pending",
    "queued", "partially_filled", "partially_filled_terminal",
    "unconfirmed", "unknown", "cancel_pending",
})
FILES = {
    "webull": "webull/orders.sqlite3",
    "robinhood_crypto": "robinhood/order_intents.json",
}


class JournalEvidenceError(ValueError):
    pass


def _decimal(value, *, allow_zero=True):
    if value is None or isinstance(value, (float, bool)):
        raise JournalEvidenceError("INVALID_LOCAL_MONETARY_VALUE")
    try:
        dec = Decimal(str(value))
    except (TypeError, ValueError, InvalidOperation):
        raise JournalEvidenceError("INVALID_LOCAL_MONETARY_VALUE") from None
    if not dec.is_finite() or dec < 0 or (dec == 0 and not allow_zero) or dec > Decimal("1e15"):
        raise JournalEvidenceError("INVALID_LOCAL_MONETARY_VALUE")
    return dec


def _safe_file(path, maximum):
    path = Path(path)
    try:
        if path.is_symlink() or not path.is_file():
            return False
        st = path.stat()
        return (stat.S_ISREG(st.st_mode) and not st.st_mode & 0o077
                and 1 <= st.st_size <= maximum)
    except OSError:
        return False


def _webull_rows(path):
    if not _safe_file(path, 30_000_000):
        raise JournalEvidenceError("PRIVATE_SQLITE_MISSING_OR_UNSAFE")
    # SQLite reader uses mode=ro, query_only and never creates/migrates a DB.
    # A bounded LIMIT prevents a corrupted journal from creating huge API output.
    conn = sqlite3.connect("file:" + str(path.absolute()) + "?mode=ro",
                           timeout=3, uri=True)
    try:
        conn.execute("PRAGMA query_only=ON")
        rows = conn.execute(
            "SELECT client_id,account,status,quantity,filled_qty,filled_price,"
            "fee,broker_id,broker_status,side,asset,created_at "
            "FROM orders ORDER BY created_at,client_id LIMIT ?",
            (MAX_RECORDS + 1,),
        ).fetchall()
        if len(rows) > MAX_RECORDS:
            raise JournalEvidenceError("JOURNAL_RECORD_LIMIT_EXCEEDED")
        return [dict(zip(
            ("client_id","account","status","quantity","filled_qty",
             "filled_price","fee","broker_id","broker_status","side",
             "asset","created_at"), row
        )) for row in rows]
    except sqlite3.Error:
        raise JournalEvidenceError("LOCAL_SQLITE_SCHEMA_OR_READ_UNVERIFIED") from None
    finally:
        conn.close()


def _robinhood_rows(path):
    if not _safe_file(path, 8_000_000):
        raise JournalEvidenceError("PRIVATE_JSON_MISSING_OR_UNSAFE")
    data = private_json(path, maximum=8_000_000)
    if not data or data.get("version") != 1 or not isinstance(data.get("orders"), list):
        raise JournalEvidenceError("LOCAL_JSON_SCHEMA_UNVERIFIED")
    rows = data["orders"]
    if len(rows) > MAX_RECORDS:
        raise JournalEvidenceError("JOURNAL_RECORD_LIMIT_EXCEEDED")
    return rows


def observe_legacy_journal(state_dir, broker):
    """Bounded, privacy-preserving all-account V1 journal observation.

    No account can inherit V2 trading permission from this output. The journal
    may cover more than one broker account; account mapping is not certified.
    """
    if broker not in FILES:
        raise ValueError("UNKNOWN_LEGACY_JOURNAL")
    result = {
        "broker": broker, "state": "UNAVAILABLE", "source": FILES[broker],
        "account_scope": "ALL_LOCAL_V1_ACCOUNTS_NOT_V2_BOUND",
        "local_record_count": None, "local_unresolved_count": None,
        "local_filled_count": None, "incomplete_fill_details": None,
        "accounts_observed": None, "local_status_counts": {},
        "broker_reconciliation_verified": False,
        "settled_cash_verified": False,
        "broker_positions_verified": False,
        "ready_for_v2_live": False, "v2_order_authorized": False,
    }
    path = Path(state_dir) / FILES[broker]
    try:
        rows = _webull_rows(path) if broker == "webull" else _robinhood_rows(path)
        ids = set()
        accounts = set()
        states = Counter()
        unresolved = 0
        filled = 0
        details_missing = 0
        for row in rows:
            if not isinstance(row, dict):
                raise JournalEvidenceError("LOCAL_ORDER_ROW_INVALID")
            identity = row.get("client_id") if broker == "webull" else row.get("client_order_id")
            account = row.get("account")
            status = row.get("status")
            if (not isinstance(identity, str) or not 1 <= len(identity) <= 160
                    or identity in ids or not isinstance(account, str)
                    or not 1 <= len(account) <= 160 or not isinstance(status, str)
                    or status not in (VALID_WEBULL if broker == "webull" else VALID_ROBINHOOD)):
                raise JournalEvidenceError("LOCAL_ORDER_IDENTITY_OR_STATE_INVALID")
            ids.add(identity)
            accounts.add(account)
            states[status] += 1
            terminal = status in (WEBULL_TERMINAL if broker == "webull" else ROBINHOOD_TERMINAL)
            if not terminal:
                unresolved += 1
            if status == ("FILLED" if broker == "webull" else "filled"):
                filled += 1
                try:
                    expected = _decimal(row.get("quantity"), allow_zero=False)
                    actual = _decimal(
                        row.get("filled_qty") if broker == "webull"
                        else row.get("filled_quantity"), allow_zero=False
                    )
                    price = _decimal(
                        row.get("filled_price") if broker == "webull"
                        else row.get("average_fill_price"), allow_zero=False
                    )
                    if expected != actual or price <= 0:
                        details_missing += 1
                    if not row.get("broker_id" if broker == "webull" else "broker_order_id"):
                        details_missing += 1
                    fee = row.get("fee" if broker == "webull" else "fee_charged")
                    if fee is None:
                        details_missing += 1
                    else:
                        _decimal(fee)
                except JournalEvidenceError:
                    details_missing += 1
            if broker == "webull" and status == "PARTIAL_TERMINAL":
                # V1 purposely retains these pending until manual reconciliation.
                pass
        result.update({
            "local_record_count": len(rows),
            "local_unresolved_count": unresolved,
            "local_filled_count": filled,
            "incomplete_fill_details": details_missing,
            "accounts_observed": len(accounts),
            "local_status_counts": dict(sorted(states.items())),
        })
        if unresolved:
            result["state"] = "LOCAL_INTENTS_UNRESOLVED"
        elif details_missing:
            result["state"] = "LOCAL_FILL_EVIDENCE_INCOMPLETE"
        elif not rows:
            result["state"] = "LOCAL_JOURNAL_EMPTY"
        else:
            result["state"] = "LOCAL_TERMINAL_RECORDS_ONLY"
    except (JournalEvidenceError, OSError, sqlite3.Error) as exc:
        result["state"] = "JOURNAL_EVIDENCE_UNAVAILABLE"
        result["reason"] = (str(exc)[:72] if isinstance(exc, JournalEvidenceError)
                            else "JOURNAL_IO_UNAVAILABLE")
    return result
