"""Unified forecast selection: built-in is always available without ML weights.

Modes:
 auto: use a healthy specialist companion if present, otherwise built-in
 built_in: deterministic market analysis, optional configured provider commentary
 advanced: prefer specialist companion, fall back to built-in with warning
"""
from __future__ import annotations
from built_in_forecast import get as native_get
from forecast_ai_review import review as selected_ai_review
from forecast_connection import (
    connection_status, research_doc, ForecastConnectionError)
def _prefer_advanced(cfg):
    return cfg.get("forecast_mode","auto") in ("auto","advanced") and (
       bool(cfg.get("forecast_url")) or bool(cfg.get("ollama_url")))

def connection(cfg):
    mode=cfg.get("forecast_mode","auto")
    extra={"requested_mode":mode,
           "built_in_available":True,
           "ai_review_requested":bool(cfg.get("forecast_ai_review",False)),
           "ai_provider":cfg.get("ai_provider","none")}
    if mode=="built_in" or not _prefer_advanced(cfg):
        return {**extra,"connected":True,"source":"nas-built-in",
                "mode":"built_in","message":"Built-in daily price/volume research; no specialized forecast models required"}
    status=connection_status(cfg)
    if status.get("connected"):
        return {**extra,**status,"mode":"advanced"}
    return {**extra,"connected":True,"source":"nas-built-in",
            "mode":"built_in","advanced_status":status.get("message","not connected"),
            "message":"Advanced forecast service unavailable; using built-in analysis automatically"}

def forecast(state,cfg,secrets):
    status=connection(cfg)
    if status["mode"]=="advanced":
        try:
            doc=research_doc(cfg,"/api/forecast")
            if isinstance(doc.get("candidates"),list):
                doc["engine"]="advanced"
                doc["research_mode"]="advanced"
                doc["connection_note"]="Specialist models running on external AI workstation"
                return doc
            # Pending specialized model service: show built-in results.
        except ForecastConnectionError:pass
    doc=native_get(state,cfg,secrets,reviewer=selected_ai_review if
                   cfg.get("forecast_ai_review") else None)
    # Never alter the cached shared copy just to decorate the response.
    doc=dict(doc)
    doc["research_mode"]="built_in"
    doc["connection_note"]=status["message"]
    return doc

def models(state,cfg,secrets):
    return {"built_in":{"available":True,"required_installation":False,
                 "analysis":"Historical daily prices, liquidity, 5/20/50-session trends, 20-day volatility"},
            "provider":{"selected":cfg.get("ai_provider","none"),
                 "review_enabled":bool(cfg.get("forecast_ai_review",False)),
                 "qualitative_only":True},
            "advanced":{"optional":True,"status":connection_status(cfg)
                  if _prefer_advanced(cfg) else {"connected":False}}}
