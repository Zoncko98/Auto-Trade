"""Read-only, authentication-gated V2 feature status; no live order authority."""
from __future__ import annotations
from pathlib import Path
import os,sqlite3
from .models import OrderState,TERMINAL
from .readonly_adapters import ReadOnlyBrokerRegistry
from .market_sources import cached_market_status

def enabled()->bool:
    return os.environ.get("AUTO_TRADER_V2_ENABLED","false").lower()=="true"

def summary(state_dir)->dict:
    status={"version":"2.0.0-alpha.3","feature_enabled":enabled(),
            "live_order_authority":False,"execution_mode":"PAPER_ONLY",
            "legacy_live_workers_untouched":True,
            "stage":"PHASE_3_AI_AND_REPLAY_LIBRARIES_NOT_ARMED",
            "store":"DISABLED" if not enabled() else "NOT_INITIALIZED",
            "intents":0,"unresolved":0,
            "missing_components":["LIVE_BROKER_WRITE_ADAPTERS","AI_RUNTIME_CONFIGURATION_AND_VALIDATION",
                "REAL_MARKET_REPLAY_VALIDATION","V2_ACCOUNT_TEMPLATE","LIVE_CUTOVER"],
            "phase3_capabilities":{"typed_ai_review":"AVAILABLE_NOT_CONNECTED",
                                   "ollama_review_transport":"AVAILABLE_NOT_CONNECTED",
                                   "synthetic_candle_replay":"AVAILABLE_NOT_SCHEDULED"}}
    try:
        # Always read-only; status never refreshes broker OAuth or sends SDK calls.
        status["broker_adapters"]=[
            row.public() for row in ReadOnlyBrokerRegistry(state_dir).inspect_all()]
        status["market_sources"]=cached_market_status(state_dir)
    except (ValueError,TypeError,OSError):
        status["broker_adapters"]=[]
        status["market_sources"]={}
        status["adapters_error"]="READ_ONLY_OBSERVATIONS_UNAVAILABLE"
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
