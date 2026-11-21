"""Read-only, authentication-gated V2 feature status; no live order authority."""
from __future__ import annotations
from pathlib import Path
from datetime import datetime,timezone
import os,sqlite3
from .models import OrderState,TERMINAL
from .readonly_adapters import ReadOnlyBrokerRegistry,private_json
from .market_sources import cached_market_status
from .readiness import explain
from .cutover_preflight import preflight

def enabled()->bool:
    return os.environ.get("AUTO_TRADER_V2_ENABLED","false").lower()=="true"

def summary(state_dir)->dict:
    status={"version":"2.0.0-alpha.21","feature_enabled":enabled(),
            "live_order_authority":False,"execution_mode":"PAPER_ONLY",
            "legacy_live_workers_untouched":True,
            "stage":"PHASE_2_SIGNED_SOURCE_GAPS_AND_READONLY_JOURNAL_PRECHECK",
            "store":"DISABLED" if not enabled() else "NOT_INITIALIZED",
            "intents":0,"unresolved":0,
            "missing_components":["LIVE_BROKER_WRITE_ADAPTERS","AI_RUNTIME_CONFIGURATION_AND_VALIDATION",
                "REAL_MARKET_REPLAY_VALIDATION","V2_ACCOUNT_TEMPLATE","LIVE_CUTOVER"],
            "phase3_capabilities":{"typed_ai_review":"AVAILABLE_SHADOW_IF_MODEL_CONFIGURED",
                                   "ollama_review_transport":"AVAILABLE_SHADOW_IF_MODEL_CONFIGURED",
                                   "synthetic_candle_replay":"ON_DEMAND_HISTORICAL_CANDLES",
                                   "recorded_replay_journal":"PERSISTENT_SEPARATE_FROM_V1",
                                   "fresh_crypto_paper":"SUPERVISED_WHEN_PAPER_ENABLED",
                                   "ai_shadow":"ADVISORY_NO_ORDER_AUTHORITY",
                                   "paper_scan_metrics":"PERSISTED_24H_AND_7D",
                                   "crypto_paper_activity":"READ_ONLY_3H_24H_GENUINE_SIM_LEDGER",
                                   "crypto_paper_economics":"CUMULATIVE_SIM_CASH_INVENTORY_AND_FEES_RECONCILED",
                                   "crypto_fee_reward_shadow":"ADVISORY_PAST_CANDLE_RESISTANCE_SIM_COSTS",
                                   "fee_shadow_journal":"PRIVATE_30D_V2_SCAN_HISTORY",
                                   "cutover_preflight":"READ_ONLY_V1_RISK_AND_JOURNAL",
                                   "schwab_stock_quote_bridge":"REUSES_V1_SCANNER_NO_EXTRA_SDK_CALLS",
                                   "schwab_stock_shadow":"SUPERVISED_READ_ONLY_WITH_GENUINE_5M_HISTORY",
                                   "broker_risk_envelopes":"V1_EFFECTIVE_BUDGET_UPPER_BOUNDS_ONLY",
                                   "ollama_fast_json_shadow":"STRUCTURED_OUTPUT_NO_REASONING",
                                   "why_no_trade":"READ_ONLY_NO_LIVE_ORDER_AUTHORITY",
                                   "v1_order_journal_audit":"WEBULL_ROBINHOOD_LOCAL_RECORDS_NEVER_BROKER_AUTHORITY",
                                   "session_window":"EQUITY_TIME_WINDOW_WEEKENDS_CALENDAR_UNVERIFIED",
                                   "four_broker_navigation":"SIX_SHARED_SECTIONS_IN_EXISTING_WORKSPACES"}}
    try:
        # Always read-only; status never refreshes broker OAuth or sends SDK calls.
        status["broker_adapters"]=[
            row.public() for row in ReadOnlyBrokerRegistry(state_dir).inspect_all()]
        status["market_sources"]=cached_market_status(state_dir)
    except (ValueError,TypeError,OSError):
        status["broker_adapters"]=[]
        status["market_sources"]={}
        status["adapters_error"]="READ_ONLY_OBSERVATIONS_UNAVAILABLE"
    # Signed Robinhood broker probe is cached read-only evidence. It never
    # grants live cutover or changes the existing V1 write permission.
    status["robinhood_signed_migration_probe"]=(
        private_json(Path(state_dir)/"v2"/"broker_migration"/"robinhood_crypto.json",
                     maximum=12000) or {
            "mode":"AUTHENTICATED_SIGNED_READ_ONLY",
            "first_blocker":"SIGNED_BROKER_PROBE_NOT_YET_RUN",
            "v2_live_order_authority":False,"cutover_ready":False})
    # Even correctly signed, cached broker observations expire. A stale
    # status must not appear as current authentication or cutover permission.
    probe=status["robinhood_signed_migration_probe"]
    try:
        observed=datetime.fromisoformat(str(probe["checked_at"]).replace("Z","+00:00"))
        if observed.tzinfo is None:raise ValueError("naive broker observation")
        age=(datetime.now(timezone.utc)-observed.astimezone(timezone.utc)).total_seconds()
    except (TypeError,ValueError,KeyError,AttributeError):
        age=float("inf")
    if not 0<=age<=1200:
        status["robinhood_signed_migration_probe"]={
            "mode":"AUTHENTICATED_SIGNED_READ_ONLY",
            "first_blocker":"SIGNED_BROKER_PROBE_STALE_OR_UNAVAILABLE",
            "report_fresh":False,
            "v2_live_order_authority":False,"cutover_ready":False}
    else:
        probe["report_fresh"]=True
        probe["v2_live_order_authority"]=False
        probe["cutover_ready"]=False
    # Observational gate explanations never grant live order authority;
    # no unauthenticated API can expose this authenticated status object.
    status["readiness_diagnostics"]=explain(
        status["broker_adapters"],status["market_sources"])
    status["cutover_preflight"]=preflight(
        state_dir,status["broker_adapters"],status["market_sources"])
    if not enabled():return status
    path=Path(state_dir)/"v2"/"events.sqlite3"
    if not path.is_file():return status
    try:
        # URI mode=ro guarantees status polling cannot create or mutate DB.
        db=sqlite3.connect("file:"+str(path.resolve())+"?mode=ro",uri=True,timeout=2)
        try:
            db.row_factory=sqlite3.Row
            rows=db.execute("SELECT state,COUNT(*) AS n FROM intents GROUP BY state").fetchall()
            counts={row["state"]:row["n"] for row in rows}
            status["intents"]=sum(counts.values())
            status["unresolved"]=sum(v for k,v in counts.items() if OrderState(k) not in TERMINAL)
            status["store"]="READY"
        finally:db.close()
    except (OSError,sqlite3.Error,ValueError):
        status["store"]="UNAVAILABLE"
    return status
