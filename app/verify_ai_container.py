"""Read-only smoke test for local AI inference inside trading worker.

A synthetic headline confirms JSON classification only, not trade skill.
This script does not contact Schwab or submit orders.
"""
from __future__ import annotations
import os
from openwebui_gateway import classify_news,GatewayUnavailable
from local_ai_gateway import installed_models,LocalAIUnavailable

def main():
    if os.getenv("AI_PROVIDER")!="local":
        raise SystemExit("AI_PROVIDER must be local")
    model=os.getenv("LOCAL_AI_MODEL","")
    models=installed_models()
    if model not in models:
        raise SystemExit("Configured model not installed in Ollama")
    print("LOCAL_AI_SERVER: PASS")
    print("LOCAL_AI_MODEL:",model)
    example=[{"title":"Synthetic neutral service check; not real financial news",
              "source":"Auto Trader integration test",
              "published_at":"2026-10-30T19:30:00+00:00"}]
    result=classify_news("F",example)
    if result.get("ticker")!="F" or result.get("calibrated_win_probability") is not None:
        raise SystemExit("Local model response contract failed")
    print("LOCAL_AI_STRUCTURED_RESPONSE: PASS")
    print("LOCAL_AI_SENTIMENT_SAMPLE:",result["sentiment"])
    print("MODEL_PROBABILITY_CALIBRATED: NO")
    print("BROKER_ORDERS_SENT: NO")

if __name__=="__main__":
    try:
        main()
    except (GatewayUnavailable,LocalAIUnavailable) as exc:
        print("LOCAL_AI_SMOKE_FAILED:",str(exc))
        raise SystemExit(2) from None
