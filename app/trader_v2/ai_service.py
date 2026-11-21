"""Typed, bounded advisory AI review for V2 paper and shadow pipelines.

No broker imports and no order authority. Transport must enforce network timeout.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Callable
import json
from .models import AIReview, AIState, Candidate, MarketSnapshot, utc

class ReviewUnavailable(RuntimeError):
    pass

class SharedAIReviewer:
    def __init__(self, transport: Callable[[str, float], str], *, model: str,
                 timeout_seconds: float = 8, ttl_seconds: int = 60,
                 clock: Callable[[], datetime] | None = None):
        if not callable(transport) or not isinstance(model, str) or not 1 <= len(model) <= 96:
            raise ValueError("Invalid AI transport or model")
        if not 0.5 <= timeout_seconds <= 60 or not 1 <= ttl_seconds <= 300:
            raise ValueError("Invalid timeout or TTL")
        self.transport, self.model = transport, model
        self.timeout_seconds, self.ttl_seconds = timeout_seconds, ttl_seconds
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._cache = {}
        self._lock = Lock()

    def review(self, candidate: Candidate, quote: MarketSnapshot) -> AIReview:
        if not isinstance(candidate, Candidate) or not isinstance(quote, MarketSnapshot):
            raise TypeError("Canonical candidate and quote required")
        now = utc(self.clock())
        if candidate.symbol != quote.symbol or candidate.asset_class != quote.asset_class:
            raise ReviewUnavailable("SIGNAL_QUOTE_MISMATCH")
        if quote.observed_at > now + timedelta(seconds=2) or (now - quote.observed_at).total_seconds() > 90:
            raise ReviewUnavailable("STALE_QUOTE")
        if candidate.signal_at > now + timedelta(seconds=2) or (now - candidate.signal_at).total_seconds() > 300:
            raise ReviewUnavailable("STALE_SIGNAL")
        key = (candidate.account_id, candidate.strategy, candidate.version,
               candidate.symbol, candidate.asset_class.value, candidate.side.value,
               candidate.signal_at, quote.source, quote.observed_at,
               str(quote.bid), str(quote.ask), str(quote.last))
        with self._lock:
            previous = self._cache.get(key)
            if previous and previous.expires_at >= now:
                return previous
        payload = {
            "instruction": "Return strict JSON: symbol, state (PASS or VETO), reason. Advisory only. No orders.",
            "candidate": {"symbol": candidate.symbol, "asset_class": candidate.asset_class.value,
                          "side": candidate.side.value, "strategy": candidate.strategy,
                          "evidence": dict(candidate.evidence)},
            "quote": {"source": quote.source, "observed_at": quote.observed_at.isoformat(),
                      "bid": str(quote.bid), "ask": str(quote.ask), "last": str(quote.last)}
        }
        request = json.dumps(payload, separators=(",", ":"), allow_nan=False)
        if len(request.encode("utf-8")) > 8192:
            raise ReviewUnavailable("INPUT_TOO_LARGE")
        try:
            response = self.transport(request, self.timeout_seconds)
            if not isinstance(response, str) or len(response.encode("utf-8")) > 8192:
                raise ReviewUnavailable("INVALID_RESPONSE_SIZE")
            data = json.loads(response)
        except ReviewUnavailable:
            raise
        except TimeoutError as exc:
            raise ReviewUnavailable("MODEL_TIMEOUT") from exc
        except Exception as exc:
            raise ReviewUnavailable("AI_UNAVAILABLE") from exc
        if not isinstance(data, dict) or set(data) != {"symbol", "state", "reason"}:
            raise ReviewUnavailable("INVALID_MODEL_SCHEMA")
        if data["symbol"] != candidate.symbol or data["state"] not in ("PASS", "VETO"):
            raise ReviewUnavailable("AI_IDENTITY_OR_STATE_MISMATCH")
        reason = data["reason"]
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 500:
            raise ReviewUnavailable("INVALID_REASON")
        finished = utc(self.clock())
        if (finished - now).total_seconds() > self.timeout_seconds + 1:
            raise ReviewUnavailable("MODEL_TIMEOUT")
        review = AIReview(AIState(data["state"]), candidate.symbol, finished,
                          finished + timedelta(seconds=self.ttl_seconds),
                          self.model, reason.strip())
        with self._lock:
            if len(self._cache) >= 512:
                self._cache.clear()
            self._cache[key] = review
        return review
