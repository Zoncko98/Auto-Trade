"""On-demand, broker-independent V2 historical paper replay.

Reads ONLY the recorded closed-bar tape created by the existing paper collector.
Runs a deterministic stock/crypto controller -> risk -> durable intent ->
SimulatedBroker pipeline. Replay bid/ask, slippage and fees are synthetic and
MUST NOT be presented as real executable broker quotes or live performance.
No network, credentials, real-broker import or order submission is possible.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import csv
import fcntl
import hashlib
import io
import json
import os
import stat

from .models import AssetClass, Candle, valid_symbol
from .replay import replay_candles

# Explicit symbol registry. Never infer asset class from the symbol spelling.
SUPPORTED = {
    "BTCUSD": AssetClass.CRYPTO, "ETHUSD": AssetClass.CRYPTO,
    "SOLUSD": AssetClass.CRYPTO, "DOGEUSD": AssetClass.CRYPTO,
    "XRPUSD": AssetClass.CRYPTO, "ADAUSD": AssetClass.CRYPTO,
    "AAPL": AssetClass.STOCK, "MSFT": AssetClass.STOCK,
    "NVDA": AssetClass.STOCK, "SPY": AssetClass.STOCK,
    "TSLA": AssetClass.STOCK,
}
MAX_TAPE_BYTES = 512_000
MAX_ROWS = 5000
MAX_CANDLES = 240
VERSION = "recorded-replay-1"
ASSUMPTIONS = {"initial_virtual_cash": "1000", "fee_bps": "5",
               "slippage_bps": "5", "synthetic_spread_bps": "10",
               "ai_mode": "OFF", "execution": "SIMULATED_ONLY"}


class ReplayUnavailable(ValueError):
    """Safe, bounded public error code for missing or invalid recordings."""


def _private_dir(path: Path):
    if path.is_symlink():
        raise ReplayUnavailable("REPLAY_DIRECTORY_UNSAFE")
    try:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        mode = path.stat().st_mode
        if not stat.S_ISDIR(mode) or mode & 0o077:
            raise ReplayUnavailable("REPLAY_DIRECTORY_UNSAFE")
    except OSError as exc:
        raise ReplayUnavailable("REPLAY_STORAGE_UNAVAILABLE") from exc


def _private_json(path: Path):
    try:
        st = path.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_mode & 0o077 or st.st_size > 65_536:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError, UnicodeError):
        return None


def _atomic_json(path: Path, data: dict):
    raw = json.dumps(data, separators=(",", ":"), sort_keys=True,
                     allow_nan=False).encode("utf-8")
    if len(raw) > 65_536:
        raise ReplayUnavailable("REPLAY_RESULT_TOO_LARGE")
    temp = path.parent / ("." + path.name + "." + os.urandom(6).hex())
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        dir_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if temp.exists():
            temp.unlink()


def _recordings(root: Path):
    tape = root / "prices.csv"
    try:
        st = tape.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_mode & 0o022:
            raise ReplayUnavailable("RECORDED_SOURCE_UNSAFE")
        if not 1 <= st.st_size <= MAX_TAPE_BYTES:
            raise ReplayUnavailable("RECORDED_SOURCE_MISSING_OR_OVERSIZED")
        raw = tape.read_bytes()
        if len(raw) > MAX_TAPE_BYTES:
            raise ReplayUnavailable("RECORDED_SOURCE_OVERSIZED")
        document = raw.decode("utf-8-sig")
    except FileNotFoundError:
        raise ReplayUnavailable("RECORDED_SOURCE_UNAVAILABLE") from None
    except (OSError, UnicodeError) as exc:
        raise ReplayUnavailable("RECORDED_SOURCE_UNAVAILABLE") from exc
    reader = csv.DictReader(io.StringIO(document))
    if reader.fieldnames != ["timestamp", "symbol", "price"]:
        raise ReplayUnavailable("RECORDED_SOURCE_SCHEMA_INVALID")
    result: dict[str, list[Candle]] = {}
    seen: set[tuple[str, datetime]] = set()
    now = datetime.now(timezone.utc)
    for i, record in enumerate(reader):
        if i >= MAX_ROWS:
            raise ReplayUnavailable("RECORDED_SOURCE_OVERSIZED")
        if not isinstance(record, dict) or set(record) != {"timestamp", "symbol", "price"}:
            raise ReplayUnavailable("RECORDED_SOURCE_SCHEMA_INVALID")
        sym = record.get("symbol")
        if sym not in SUPPORTED:
            continue  # Unknown symbols cannot silently be assigned an asset class.
        try:
            valid_symbol(sym)
            opened = datetime.fromisoformat(record["timestamp"].replace("Z", "+00:00"))
            if opened.tzinfo is None:
                raise ValueError("Naive candle")
            closed = opened.astimezone(timezone.utc) + timedelta(minutes=1)
            close = Decimal(record["price"])
            candle = Candle(sym, closed, close, closed=True)
        except (ValueError, InvalidOperation, TypeError, KeyError, OverflowError):
            raise ReplayUnavailable("RECORDED_CANDLE_INVALID") from None
        if closed > now:
            continue  # Never pretend the currently forming bar has closed.
        key = sym, closed
        if key in seen:
            raise ReplayUnavailable("RECORDED_CANDLE_DUPLICATE")
        seen.add(key)
        result.setdefault(sym, []).append(candle)
    for sym in result:
        result[sym].sort(key=lambda c: c.observed_at)
        result[sym] = result[sym][-MAX_CANDLES:]
    return hashlib.sha256(raw).hexdigest(), result


def replay_status(state_dir) -> dict:
    """Read-only dashboard status; does not initialize any account or database."""
    try:
        digest, streams = _recordings(Path(state_dir))
        available = [{
            "symbol": symbol, "asset_class": SUPPORTED[symbol].value,
            "closed_bars": len(bars), "start": bars[0].observed_at.isoformat(),
            "end": bars[-1].observed_at.isoformat(),
            "replayable": len(bars) >= 10
        } for symbol, bars in sorted(streams.items()) if bars]
        state = "AVAILABLE" if any(x["replayable"] for x in available) else "INSUFFICIENT_CANDLES"
    except ReplayUnavailable as exc:
        digest = None
        available = []
        state = str(exc)
    last = _private_json(Path(state_dir) / "v2" / "recorded_replays" / "latest.json")
    return {
        "state": state, "symbols": available,
        "last_report": last,
        "source": "RECORDED_V1_PAPER_CLOSED_BARS",
        "market_executable": False, "live_orders_authorized": False,
        "ai_invoked": False,
        "synthetic_execution_assumptions": ASSUMPTIONS,
    }


@contextmanager
def _single_replay(root: Path):
    base = root / "v2"
    _private_dir(base)
    name = base / "recorded_replays"
    _private_dir(name)
    lock_path = base / "recorded_replay.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_mode & 0o077:
            raise ReplayUnavailable("REPLAY_LOCK_UNSAFE")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ReplayUnavailable("REPLAY_ALREADY_RUNNING") from None
        yield name
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def run_recorded_replay(state_dir, symbol: str) -> dict:
    """Operator-triggered, historical-only simulation with permanent V2 journals."""
    if not isinstance(symbol, str) or symbol not in SUPPORTED:
        raise ReplayUnavailable("UNSUPPORTED_RECORDED_SYMBOL")
    root = Path(state_dir)
    digest, streams = _recordings(root)
    candles = streams.get(symbol, [])
    if len(candles) < 10:
        raise ReplayUnavailable("NOT_ENOUGH_CLOSED_CANDLES")
    identity = json.dumps({"version": VERSION, "source_sha256": digest,
        "symbol": symbol, "asset": SUPPORTED[symbol].value,
        "assumptions": ASSUMPTIONS}, sort_keys=True)
    run_id = hashlib.sha256(identity.encode()).hexdigest()[:32]
    with _single_replay(root) as base:
        workspace = base / run_id
        _private_dir(workspace)
        report_path = workspace / "result.json"
        existing = _private_json(report_path)
        if existing:
            return existing
        result = replay_candles(
            candles, SUPPORTED[symbol], workspace=workspace,
            starting_cash=ASSUMPTIONS["initial_virtual_cash"],
            fee_bps=ASSUMPTIONS["fee_bps"],
            slippage_bps=ASSUMPTIONS["slippage_bps"],
            spread_bps=ASSUMPTIONS["synthetic_spread_bps"])
        report = {
            "run_id": run_id, "source_sha256": digest, "version": VERSION,
            "source": "RECORDED_V1_PAPER_CLOSED_BARS",
            "simulated_only": True, "broker_credentials_used": False,
            "market_executable": False, "live_orders_authorized": False,
            "ai_invoked": False, "assumptions": ASSUMPTIONS,
            "recording_start": candles[0].observed_at.isoformat(),
            "recording_end": candles[-1].observed_at.isoformat(),
            **result,
        }
        _atomic_json(report_path, report)
        # An interruption between these writes never creates another order:
        # re-running finds the immutable run_id and reconciles original intents.
        _atomic_json(base / "latest.json", report)
        return report
