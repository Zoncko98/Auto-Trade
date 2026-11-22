"""Isolated advisory Ollama shadow review for V2 public crypto paper signals.

Shadow decisions are evidence only: never veto or create a paper order, never
touch the live order pipeline, and never grant authority to live brokers.
"""
from __future__ import annotations
from datetime import datetime,timezone
import os
import time

from .ai_service import SharedAIReviewer, ReviewUnavailable
from .ollama_transport import OllamaReviewTransport
from .models import AIState, Candidate, MarketSnapshot

def shadow_review(candidate: Candidate,quote: MarketSnapshot,*,now=None,env=None):
    if not isinstance(candidate,Candidate) or not isinstance(quote,MarketSnapshot):
        raise TypeError("Canonical candidate and public quote required")
    config=env if env is not None else os.environ
    model=config.get("AI_MODEL","")
    endpoint=config.get("AI_OLLAMA_URL","")
    if not isinstance(model,str) or not model.strip() or not isinstance(endpoint,str) or not endpoint:
        return {"state":"NOT_CONFIGURED","model":None,
                "reason":"No configured shared Ollama model",
                "changed_order_authority":False}
    start=time.monotonic()
    try:
        transport=OllamaReviewTransport(endpoint,model)
        reviewer=SharedAIReviewer(transport,model=model,
            timeout_seconds=18,ttl_seconds=50,
            clock=lambda:datetime.now(timezone.utc))
        review=reviewer.review(candidate,quote)
        if review.state not in (AIState.PASS,AIState.VETO):
            raise ReviewUnavailable("INVALID_SHADOW_REVIEW")
        return {"state":review.state.value,
                "model":review.model,
                "reason":review.reason[:160],
                "latency_ms":int((time.monotonic()-start)*1000),
                "reviewed_at":review.reviewed_at.isoformat(),
                "expires_at":review.expires_at.isoformat(),
                "changed_order_authority":False}
    except Exception as exc:
        code=(str(exc)[:90] if isinstance(exc,ReviewUnavailable)
              else "OLLAMA_SHADOW_UNAVAILABLE")
        return {"state":"UNAVAILABLE","model":model[:96],
                "reason":code,"latency_ms":int((time.monotonic()-start)*1000),
                "changed_order_authority":False}
