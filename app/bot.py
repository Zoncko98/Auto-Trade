"""Fail-closed monitoring process for the trading-bot PAPER sandbox.

No Schwab integration, API orders, or live brokerage connections are present.
Data must be separately supplied as timestamped CSV observations.
"""
import json
import logging
import math
import os
import signal
import sys
import time
from pathlib import Path

from ai_review import OllamaReviewer
from cloud_models import CloudReviewRouter
from dashboard_control import read_control, write_atomic, now_utc
from paper_engine import PaperEngine
from risk_controls import RiskLimits


def boolean(name: str, default: str = "false") -> bool:
    value = os.getenv(name, default).strip().lower()
    if value not in ("true", "false"):
        raise ValueError(f"{name} must be true or false")
    return value == "true"


def configuration():
    if boolean("LIVE_TRADING"):
        raise ValueError("LIVE_TRADING=true is prohibited: brokerage orders are not implemented")
    if boolean("ALLOW_OPTIONS") or boolean("ALLOW_MARGIN") or boolean("ALLOW_SHORT_SELLING"):
        raise ValueError("Options, margin, and short selling are prohibited")
    if not boolean("ALLOW_STOCKS", "true") and not boolean("ALLOW_ETFS", "true"):
        raise ValueError("At least one asset class must be enabled")
    capital = float(os.getenv("INITIAL_CAPITAL", "100"))
    target = float(os.getenv("PROFIT_TARGET", "100"))
    duration = int(os.getenv("EXPERIMENT_DAYS", "100"))
    limits = RiskLimits(
        initial_capital=capital,
        max_position_pct=float(os.getenv("MAX_POSITION_PCT", "25")),
        max_daily_loss=float(os.getenv("MAX_DAILY_LOSS", "5")),
        max_open_positions=int(os.getenv("MAX_OPEN_POSITIONS", "3")),
    )
    # Validation is performed by RiskControls in PaperEngine.
    if not math.isfinite(target) or target <= 0 or duration <= 0:
        raise ValueError("Invalid profit target or experiment duration")
    interval = int(os.getenv("LOOP_INTERVAL_SECONDS", "30"))
    if not 5 <= interval <= 3600:
        raise ValueError("LOOP_INTERVAL_SECONDS must be 5..3600")
    symbols = {s.strip().upper() for s in os.getenv("PAPER_SYMBOLS", "SPY").split(",") if s.strip()}
    if not symbols or any(not s.isalnum() or len(s) > 8 for s in symbols):
        raise ValueError("PAPER_SYMBOLS must contain simple ticker symbols")
    return limits, target, duration, interval, symbols


def main() -> int:
    try:
        limits, target, duration, interval, symbols = configuration()
        log_dir = Path(os.getenv("LOG_DIR", "/logs"))
        log_dir.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
            handlers=[logging.StreamHandler(), logging.FileHandler(log_dir / "bot.log")])
        state_dir = Path(os.getenv("STATE_DIR", "/state"))
        reviewer = OllamaReviewer(
            url=os.getenv("AI_OLLAMA_URL", ""),
            model=os.getenv("AI_MODEL", ""),
            timeout_seconds=float(os.getenv("AI_REVIEW_TIMEOUT_SECONDS", "5")),
            token=os.getenv("AI_OLLAMA_TOKEN", ""),
        )
        engine = PaperEngine(
            state_path=state_dir / "paper_account.json",
            limits=limits,
            allowed_symbols=symbols,
            allow_fractional=boolean("ALLOW_FRACTIONAL_SHARES", "true"),
            reviewer=CloudReviewRouter(state_dir, fallback=reviewer))
    except (ValueError, OSError, TypeError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    price_path = state_dir / "prices.csv"
    control_path = state_dir / "control.json"
    runtime_path = state_dir / "runtime_status.json"
    logging.info("PAPER-ONLY monitoring started. Live order submission is disabled.")
    logging.info("Capital $%.2f, profit target $%.2f, duration %d days", limits.initial_capital, target, duration)
    logging.info("Symbols: %s; maximum position: %.1f%%; maximum daily loss: $%.2f; maximum positions: %d",
                 ",".join(sorted(symbols)), limits.max_position_pct, limits.max_daily_loss, limits.max_open_positions)
    logging.info("Input: %s. No real-time market data provider is configured.", price_path)
    logging.info("AI review router enabled (cloud or local if configured). Entry requires explicit approval.")
    logging.info("Cloud provider credentials are stored in /state; never exposed to the browser.")
    stopping = False

    def stop(_signal, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    last_heartbeat = 0.0
    last_mode = None
    once = "--once" in sys.argv
    while not stopping:
        mode = "stopped"
        revision = -1
        last_error = ""
        try:
            # Missing or invalid control is always STOPPED, never auto-running.
            control = read_control(control_path)
            mode, revision = control["mode"], control["revision"]
            engine.set_trade_settings(control["settings"])
            if mode != last_mode:
                logging.info("Strategy mode: %s (revision %s)", mode, revision)
                last_mode = mode
            results = engine.ingest_csv(price_path) if mode == "running" else []
            for result in results:
                if result.startswith("PAPER_"):
                    logging.info("%s (simulated only)", result)
                elif result == "AI_REJECTED":
                    decision = engine.state.get("reviews", [])[-1]
                    logging.info("AI vetoed paper entry: %s: %s",
                                 decision.get("symbol"), decision.get("reason"))
            now = time.monotonic()
            if now - last_heartbeat >= 300 or once:
                logging.info("Heartbeat. Mode=%s paper equity $%.2f, cash $%.2f, trades %d, halted %s",
                             mode, engine.equity(), engine.state["cash"],
                             len(engine.state["trades"]), engine.state["halted"])
                last_heartbeat = now
                with (state_dir / "performance.jsonl").open("a", encoding="utf-8") as history:
                    history.write(json.dumps({
                        "timestamp": now_utc(), "equity": round(engine.equity(), 2),
                        "cash": round(engine.state["cash"], 2),
                        "reserved_profit": round(engine.state.get("reserved_profit", 0), 2),
                        "mode": mode,
                    }, allow_nan=False) + "\n")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            mode = "error"
            last_error = f"{type(exc).__name__}: {str(exc)[:160]}"
            logging.exception("Processing paused by error (no live orders): %s", exc)
        try:
            write_atomic(runtime_path, {
                "updated_at": now_utc(), "mode": mode, "revision": revision,
                "last_error": last_error, "paper_only": True,
                "ai_model_configured": bool(reviewer.url and reviewer.model),
                "equity": round(engine.equity(), 2),
                "cash": round(engine.state["cash"], 2),
                "reserved_profit": round(engine.state.get("reserved_profit", 0), 2),
                "trades": len(engine.state["trades"]),
                "daily_target_reached": bool(engine.state.get("daily_target_reached", False)),
                "daily_growth_target_pct": engine.trade_settings["daily_growth_target_pct"],
                "day_start_equity": engine.state.get("day_start_equity", limits.initial_capital),
            })
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logging.error("Unable to record runtime heartbeat: %s", exc)
        if once:
            return 1 if last_error else 0
        time.sleep(interval)
    logging.info("Paper monitor stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
