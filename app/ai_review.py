"""Conservative AI veto for paper trade candidates (local Ollama only).

Unconfigured, unreachable, malformed, or uncertain model responses DENY entries.
The model has no brokerage credentials and cannot alter deterministic risk limits.
"""
from __future__ import annotations

import ipaddress
import json
import math
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["APPROVE", "REJECT"]},
        "reason": {"type": "string"},
        "risk_flags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["decision", "reason", "risk_flags"],
    "additionalProperties": False,
}
SYSTEM_PROMPT = (
    "You are a conservative second-pass reviewer of PAPER-ONLY trade candidates. "
    "You may veto, but you may never create a trade, change quantity, or override risk checks. "
    "Assess only numeric, dated information provided in the candidate; do not invent "
    "news, fundamentals, or forecasts. Data is limited and profits are not guaranteed. "
    "If evidence is inadequate, favor REJECT. Return only the prescribed JSON object "
    "with decision APPROVE or REJECT, a short reason, and a list of risk_flags."
)


@dataclass(frozen=True)
class ReviewDecision:
    approved: bool
    reason: str
    model: str
    risk_flags: tuple[str, ...] = ()
    provider_details: tuple[dict, ...] = ()
    estimated_cost_usd: float = 0.0


class OllamaReviewer:
    def __init__(self, url: str = "", model: str = "", timeout_seconds: float = 5.0,
                 token: str = ""):
        self.url = url.strip()
        self.model = model.strip()
        self.token = token.strip()
        self.timeout_seconds = float(timeout_seconds)
        if not (0.5 <= self.timeout_seconds <= 20 and math.isfinite(self.timeout_seconds)):
            raise ValueError("AI timeout must be between 0.5 and 20 seconds")
        if bool(self.url) != bool(self.model):
            raise ValueError("AI_OLLAMA_URL and AI_MODEL must both be set or both omitted")
        if self.url:
            parsed = urlsplit(self.url)
            if parsed.scheme != "http" or parsed.path not in ("/api/generate", "/ollama/api/generate"):
                raise ValueError("AI_OLLAMA_URL must point to a supported local Ollama API")
            if parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError("AI URL must not contain credentials, query or fragment")
            host = parsed.hostname or ""
            try:
                ip = ipaddress.ip_address(host)
                allowed = ip.is_private or ip.is_loopback
            except ValueError:
                allowed = host in ("ollama", "host.docker.internal", "localhost")
            if not allowed:
                raise ValueError("AI endpoint must be on a local/private network")
            if parsed.port is None:
                raise ValueError("AI endpoint must specify a port")
        if self.token and not self.url:
            raise ValueError("AI token requires a configured endpoint")
        if len(self.model) > 100 or len(self.url) > 300 or len(self.token) > 8192:
            raise ValueError("AI configuration is too long")

    def review(self, candidate: dict) -> ReviewDecision:
        if not self.url:
            return ReviewDecision(False, "AI model not configured; entry blocked", "unconfigured")
        try:
            # No untrusted prose or instructions enter the reviewer. Only machine data.
            prompt = json.dumps(candidate, allow_nan=False, sort_keys=True)
            payload = json.dumps({
                "model": self.model,
                "system": SYSTEM_PROMPT,
                "prompt": "Review the following simulated candidate JSON: " + prompt,
                "format": RESPONSE_SCHEMA,
                "options": {"temperature": 0},
                "stream": False,
                "keep_alive": "1m",
            }).encode("utf-8")
            headers = {"Content-Type": "application/json"}
            if self.token:
                headers["Authorization"] = "Bearer " + self.token
            req = Request(self.url, data=payload, method="POST", headers=headers)
            with urlopen(req, timeout=self.timeout_seconds) as response:
                raw = response.read(16385)
            if len(raw) > 16384:
                raise ValueError("AI response too large")
            envelope = json.loads(raw)
            if envelope.get("done") is not True:
                raise ValueError("AI generation incomplete")
            message = envelope.get("response")
            if not isinstance(message, str):
                raise ValueError("AI response missing text")
            decision = json.loads(message)
            if not isinstance(decision, dict) or set(decision) != {"decision", "reason", "risk_flags"}:
                raise ValueError("AI response has unexpected fields")
            outcome = decision["decision"]
            reason = decision["reason"]
            flags = decision["risk_flags"]
            if outcome not in ("APPROVE", "REJECT"):
                raise ValueError("AI returned invalid decision")
            if not isinstance(reason, str) or not reason.strip() or len(reason) > 240:
                raise ValueError("AI response has invalid reason")
            if not isinstance(flags, list) or len(flags) > 8 or any(
                not isinstance(x, str) or not x or len(x) > 120 for x in flags
            ):
                raise ValueError("AI risk flags invalid")
            approved = outcome == "APPROVE" and len(flags) == 0
            return ReviewDecision(approved, reason.strip(), self.model, tuple(flags))
        except (HTTPError, URLError, TimeoutError, OSError, ValueError,
                TypeError, KeyError, json.JSONDecodeError) as exc:
            # Do not log or surface remote response bodies, credentials, or request contents.
            return ReviewDecision(False, f"AI unavailable or invalid ({type(exc).__name__})", self.model)
