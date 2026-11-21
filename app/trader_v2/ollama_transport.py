"""Strict Ollama JSON transport for V2 advisory AI reviews.

Configuration is trusted operator input. No model output is executable, and this
module does not import broker adapters or access credentials.
"""
from __future__ import annotations
import json
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

class OllamaReviewTransport:
    def __init__(self, endpoint: str, model: str):
        url = urlsplit(endpoint)
        if (url.scheme not in ("http", "https") or not url.hostname
                or url.username or url.password or url.query or url.fragment
                or url.path not in ("", "/")
                or not isinstance(model, str) or not 1 <= len(model) <= 96):
            raise ValueError("Invalid Ollama endpoint or model")
        self.url = endpoint.rstrip("/") + "/api/chat"
        self.model = model

    def __call__(self, request: str, timeout: float) -> str:
        if not isinstance(request, str) or len(request.encode("utf-8")) > 8192:
            raise ValueError("Unbounded advisory request")
        body = json.dumps({
            "model": self.model,
            "stream": False,
            # Ollama supports structured JSON schema constraints directly.
            # The model's internal reasoning stream is not needed for advisory
            # decisions and had exceeded the six-second V2 budget.
            "think": False,
            "format": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "state": {"type": "string", "enum": ["PASS", "VETO"]},
                    "reason": {"type": "string"}
                },
                "required": ["symbol", "state", "reason"],
                "additionalProperties": False
            },
            "options": {"temperature": 0, "num_predict": 90, "num_ctx": 2048},
            "messages": [{"role": "system", "content": (
                "Return only concise JSON: symbol, state PASS or VETO, and a "
                "short evidence-based reason. No broker orders or invented data.")},
                         {"role": "user", "content": request}],
        }, separators=(",", ":")).encode("utf-8")
        req = Request(self.url, body, {"Content-Type": "application/json"}, method="POST")
        with urlopen(req, timeout=timeout) as response:
            if response.status != 200:
                raise ValueError("Ollama returned non-success status")
            raw = response.read(16385)
        if len(raw) > 16384:
            raise ValueError("Ollama response too large")
        result = json.loads(raw)
        if not isinstance(result, dict) or not isinstance(result.get("message"), dict):
            raise ValueError("Invalid Ollama response")
        content = result["message"].get("content")
        if not isinstance(content, str):
            raise ValueError("Missing Ollama message content")
        return content
