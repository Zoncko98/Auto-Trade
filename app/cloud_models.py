"""Official cloud-model adapters and fail-closed multi-model paper-trade veto.

Never send account credentials, browser cookies, positions belonging to a real
brokerage, or raw logs to providers. Inputs are bounded numeric candidate data.
Model approval is advisory and cannot override deterministic position controls.
"""
from __future__ import annotations
import json
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from ai_review import ReviewDecision, SYSTEM_PROMPT
from dashboard_control import now_utc, write_atomic

PROVIDER_IDS = ("openai", "gemini", "anthropic", "azure")
PROVIDER_LABELS = {
    "openai": "OpenAI API",
    "gemini": "Google Gemini API",
    "anthropic": "Anthropic Claude API",
    "azure": "Microsoft Foundry API",
}
MAX_RESPONSE = 24_576
MODEL_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
# Every request goes to a fixed vendor URL except for Azure's restricted hostname.
URLS = {
    "openai": "https://api.openai.com/v1/responses",
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
    "anthropic": "https://api.anthropic.com/v1/messages",
}
SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "decision": {"type": "string", "enum": ["APPROVE", "REJECT"]},
        "reason": {"type": "string"},
        "risk_flags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["decision", "reason", "risk_flags"],
}


def default_cloud_config():
    return {
        "revision": 0,
        "enabled": False,
        "mode": "single",
        "required_approvals": 2,
        "max_daily_calls": 20,
        "max_daily_estimated_usd": 0.10,
        "providers": {
            provider: {
                "enabled": False,
                "model": "",
                "input_usd_per_million": 0.0,
                "output_usd_per_million": 0.0,
                "endpoint": "",
            } for provider in PROVIDER_IDS
        },
        "updated_at": now_utc(),
    }


def valid_azure_endpoint(value: str) -> str:
    from urllib.parse import urlsplit
    p = urlsplit(value)
    host = (p.hostname or "").lower()
    allowed = any(host.endswith("." + suffix) for suffix in (
        "services.ai.azure.com", "openai.azure.com", "models.ai.azure.com"))
    if (p.scheme != "https" or not allowed or p.username or p.password
            or p.fragment or p.port not in (None, 443)):
        raise ValueError("Microsoft endpoint must be an authorized Azure Foundry HTTPS host")
    if p.path not in ("/models/chat/completions", "/openai/v1/chat/completions"):
        raise ValueError("Microsoft endpoint must be a chat-completions endpoint")
    params = urllib.parse.parse_qs(p.query, strict_parsing=True) if p.query else {}
    if any(k != "api-version" or len(v) != 1 for k,v in params.items()):
        raise ValueError("Unsupported Microsoft endpoint query")
    if len(value) > 400:
        raise ValueError("Endpoint too long")
    return value


def validate_cloud_config(data: dict) -> dict:
    if not isinstance(data, dict) or set(data) != set(default_cloud_config()):
        raise ValueError("Invalid cloud configuration structure")
    rev = data["revision"]
    if isinstance(rev, bool) or not isinstance(rev, int) or rev < 0:
        raise ValueError("Invalid cloud revision")
    if type(data["enabled"]) is not bool:
        raise ValueError("Cloud enabled must be boolean")
    if data["mode"] not in ("single", "consensus"):
        raise ValueError("Invalid AI voting mode")
    approvals = data["required_approvals"]
    if type(approvals) is not int or not 1 <= approvals <= len(PROVIDER_IDS):
        raise ValueError("Approvals must be from 1 to 4")
    calls = data["max_daily_calls"]
    if type(calls) is not int or not 1 <= calls <= 500:
        raise ValueError("Daily request cap out of range")
    budget = data["max_daily_estimated_usd"]
    if isinstance(budget, bool) or not isinstance(budget,(int,float)) or not math.isfinite(budget) or not .01 <= budget <= 5.0:
        raise ValueError("Invalid estimated daily dollar cap")
    providers = data["providers"]
    if not isinstance(providers, dict) or set(providers) != set(PROVIDER_IDS):
        raise ValueError("Expected four named providers")
    clean = {}
    for provider, settings in providers.items():
        if not isinstance(settings,dict) or set(settings) != set(default_cloud_config()["providers"][provider]):
            raise ValueError("Invalid provider settings: " + provider)
        if type(settings["enabled"]) is not bool:
            raise ValueError("Provider enabled must be boolean")
        model = settings["model"]
        if not isinstance(model,str) or (model and not MODEL_RE.fullmatch(model)):
            raise ValueError("Invalid model identifier: " + provider)
        inp = settings["input_usd_per_million"]
        out = settings["output_usd_per_million"]
        for value in (inp,out):
            if isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value) or not 0 <= value <= 10000:
                raise ValueError("Invalid model pricing: " + provider)
        endpoint = settings["endpoint"]
        if not isinstance(endpoint,str):
            raise ValueError("Invalid endpoint")
        if provider == "azure" and endpoint:
            endpoint = valid_azure_endpoint(endpoint)
        elif provider != "azure" and endpoint:
            raise ValueError("Custom endpoints prohibited for " + provider)
        if settings["enabled"] and (not model or inp <= 0 or out <= 0 or (provider=="azure" and not endpoint)):
            raise ValueError("Enabled provider requires model and positive token rates (and Azure endpoint)")
        clean[provider] = {
            "enabled": settings["enabled"], "model": model,
            "input_usd_per_million": round(float(inp),6),
            "output_usd_per_million": round(float(out),6),
            "endpoint": endpoint,
        }
    if data["enabled"]:
        num = sum(v["enabled"] for v in clean.values())
        if num < (approvals if data["mode"]=="consensus" else 1):
            raise ValueError("Not enough providers enabled for selected approval rule")
    updated_at = data["updated_at"]
    if not isinstance(updated_at,str) or len(updated_at)>70:
        raise ValueError("Invalid update time")
    return {
        "revision": rev, "enabled": data["enabled"], "mode": data["mode"],
        "required_approvals": approvals, "max_daily_calls": calls,
        "max_daily_estimated_usd": round(float(budget),4),
        "providers": clean, "updated_at": updated_at,
    }


def read_cloud_config(path: Path):
    if not Path(path).exists():
        return default_cloud_config()
    return validate_cloud_config(json.loads(Path(path).read_text(encoding="utf-8")))


def read_cloud_keys(path: Path) -> dict:
    if not Path(path).exists():
        return {}
    if Path(path).stat().st_size > 8192:
        raise ValueError("Credential file is too large")
    keys = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(keys, dict) or set(keys) - set(PROVIDER_IDS):
        raise ValueError("Invalid cloud secret store")
    if any(not isinstance(x,str) or len(x)>1000 for x in keys.values()):
        raise ValueError("Invalid cloud key value")
    return keys


def set_cloud_key(path: Path, provider: str, key: str | None):
    if provider not in PROVIDER_IDS:
        raise ValueError("Unknown provider")
    keys=read_cloud_keys(path)
    if key is None:
        keys.pop(provider,None)
    else:
        if not isinstance(key,str) or not 12 <= len(key) <= 1000 or "\n" in key or "\r" in key:
            raise ValueError("Invalid API key format")
        keys[provider]=key.strip()
    write_atomic(path,keys)
    return bool(keys.get(provider))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        return None


def _http_json(url: str, key: str, payload: dict, provider: str, timeout: float=8.0):
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if provider == "openai":
        headers["Authorization"] = "Bearer " + key
    elif provider == "gemini":
        headers["x-goog-api-key"] = key
    elif provider == "anthropic":
        headers["x-api-key"] = key
        headers["anthropic-version"] = "2023-06-01"
    else:
        headers["api-key"] = key
    req=urllib.request.Request(url,data=json.dumps(payload,separators=(",",":")).encode("utf-8"),
                               headers=headers,method="POST")
    # No environment proxies, hostname substitutions or redirects for credentials.
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    try:
        with opener.open(req,timeout=timeout) as res:
            if res.status != 200:
                raise RuntimeError("Cloud response status " + str(res.status))
            data=res.read(MAX_RESPONSE+1)
            if len(data)>MAX_RESPONSE:
                raise ValueError("Cloud response exceeded limit")
            return json.loads(data)
    except urllib.error.HTTPError as exc:
        raise RuntimeError("Provider returned HTTP " + str(exc.code)) from None
    except (urllib.error.URLError,TimeoutError,OSError) as exc:
        raise RuntimeError("Provider connection failed: " + type(exc).__name__) from None


def _parse_model_decision(text: str):
    if not isinstance(text,str) or len(text)>8000:
        raise ValueError("Model response invalid or too long")
    obj=json.loads(text)
    if not isinstance(obj,dict) or set(obj)!=set(SCHEMA["required"]):
        raise ValueError("Unexpected model response fields")
    if obj["decision"] not in ("APPROVE","REJECT"):
        raise ValueError("Invalid model decision")
    if not isinstance(obj["reason"],str) or not 1<=len(obj["reason"].strip())<=240:
        raise ValueError("Missing or excessive model reason")
    flags=obj["risk_flags"]
    if not isinstance(flags,list) or len(flags)>8 or any(
        not isinstance(x,str) or not 1<=len(x)<=100 for x in flags
    ):
        raise ValueError("Invalid model risk flags")
    return obj["decision"]=="APPROVE" and not flags,obj["reason"].strip(),tuple(flags)


def _model_request(provider: str, model: str, key: str, endpoint: str, candidate: dict):
    prompt="Evaluate this PAPER-ONLY trade candidate. Respond with the required JSON:\n" + json.dumps(
        candidate,separators=(",",":"),sort_keys=True,allow_nan=False)
    if len(prompt)>6000:
        raise ValueError("Candidate too long")
    if provider=="openai":
        body={
            "model":model,"instructions":SYSTEM_PROMPT,"input":prompt,
            "max_output_tokens":450, "store":False,
            "text":{"format":{"type":"json_schema","name":"trade_review","strict":True,"schema":SCHEMA}},
        }
        response=_http_json(URLS["openai"],key,body,provider)
        if response.get("status")!="completed":
            raise ValueError("Incomplete OpenAI response")
        parts=[]
        for item in response.get("output",[]):
            if not isinstance(item,dict):continue
            for content in item.get("content",[]):
                if content.get("type")=="output_text" and isinstance(content.get("text"),str):
                    parts.append(content["text"])
        result="".join(parts)
        usage=response.get("usage") or {}
        inp=int(usage.get("input_tokens",0))
        out=int(usage.get("output_tokens",0))
    elif provider=="gemini":
        body={
            "systemInstruction":{"parts":[{"text":SYSTEM_PROMPT}]},
            "contents":[{"role":"user","parts":[{"text":prompt}]}],
            "generationConfig":{
                "responseMimeType":"application/json",
                "responseSchema":SCHEMA,"maxOutputTokens":450,
            },
        }
        url=URLS["gemini"]+"/models/"+urllib.parse.quote(model,safe="-_.")+":generateContent"
        response=_http_json(url,key,body,provider)
        candidates=response.get("candidates") or []
        if not candidates or candidates[0].get("finishReason")!="STOP":
            raise ValueError("Incomplete or filtered Gemini response")
        result="".join(x.get("text","") for x in candidates[0].get("content",{}).get("parts",[]))
        usage=response.get("usageMetadata") or {}
        inp=int(usage.get("promptTokenCount",0))
        out=int(usage.get("candidatesTokenCount",0))
    elif provider=="anthropic":
        body={"model":model,"max_tokens":450,"system":SYSTEM_PROMPT,
              "messages":[{"role":"user","content":prompt}]}
        response=_http_json(URLS["anthropic"],key,body,provider)
        if response.get("stop_reason")!="end_turn":
            raise ValueError("Incomplete Claude response")
        result="".join(x.get("text","") for x in response.get("content",[]) if x.get("type")=="text")
        usage=response.get("usage") or {}
        inp=int(usage.get("input_tokens",0))
        out=int(usage.get("output_tokens",0))
    else:
        url=valid_azure_endpoint(endpoint)
        body={"model":model,"messages":[
            {"role":"system","content":SYSTEM_PROMPT},
            {"role":"user","content":prompt},
        ],"max_tokens":450,"response_format":{"type":"json_object"}}
        response=_http_json(url,key,body,"azure")
        choices=response.get("choices") or []
        if not choices or choices[0].get("finish_reason")!="stop":
            raise ValueError("Incomplete Microsoft model response")
        result=choices[0].get("message",{}).get("content","")
        usage=response.get("usage") or {}
        inp=int(usage.get("prompt_tokens",0))
        out=int(usage.get("completion_tokens",0))
    approved,reason,flags=_parse_model_decision(result)
    if not (0<=inp<=100000 and 0<=out<=100000):
        raise ValueError("Invalid token usage")
    return {"approved":approved,"reason":reason,"flags":flags,
            "input_tokens":inp,"output_tokens":out}


class CloudReviewRouter:
    """On-demand cloud review. Deterministic price and capital checks run elsewhere."""
    def __init__(self, state_dir: Path, fallback=None):
        self.state_dir=Path(state_dir)
        self.fallback=fallback

    def _usage_today(self):
        path=self.state_dir/"cloud_usage.jsonl"
        today=datetime.now(timezone.utc).date().isoformat()
        calls=0
        estimate=0.
        if not path.exists():return calls,estimate
        if path.stat().st_size>5_000_000:
            raise ValueError("Usage log exceeds maximum allowed size")
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                record=json.loads(line)
                if record.get("date")==today:
                    calls+=1
                    estimate+=float(record.get("reserved_estimate_usd",0))
        return calls,estimate

    def _reserve(self, provider, cfg, settings):
        calls,spent=self._usage_today()
        # Conservative upper-budget estimate, not the provider's actual invoice.
        estimate=round((3000*settings["input_usd_per_million"]+
                        500*settings["output_usd_per_million"])/1_000_000,6)
        if calls>=cfg["max_daily_calls"]:
            raise ValueError("Daily review request limit reached")
        if spent+estimate>cfg["max_daily_estimated_usd"]:
            raise ValueError("Daily estimated AI budget exhausted")
        path=self.state_dir/"cloud_usage.jsonl"
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open("a",encoding="utf-8") as stream:
            stream.write(json.dumps({
                "date":datetime.now(timezone.utc).date().isoformat(),
                "timestamp":now_utc(), "provider":provider,
                "model":settings["model"],"reserved_estimate_usd":estimate,
            },allow_nan=False)+"\n")
            stream.flush()
            os.fsync(stream.fileno())
        return estimate

    def review(self,candidate: dict) -> ReviewDecision:
        try:
            config=read_cloud_config(self.state_dir/"cloud_config.json")
            if not config["enabled"]:
                return (self.fallback.review(candidate) if self.fallback
                        else ReviewDecision(False,"Cloud AI not enabled","unconfigured"))
            keys=read_cloud_keys(self.state_dir/"cloud_keys.json")
            selected=[x for x in PROVIDER_IDS if config["providers"][x]["enabled"]]
            if config["mode"]=="single":
                selected=selected[:1]
            votes=[]
            estimate_total=0.
            for provider in selected:
                settings=config["providers"][provider]
                key=keys.get(provider)
                if not key:
                    votes.append({"provider":provider,"model":settings["model"],
                                  "approved":False,"reason":"Provider credentials missing","flags":["no_credentials"]})
                    continue
                try:
                    reserved=self._reserve(provider,config,settings)
                    estimate_total+=reserved
                    reply=_model_request(provider,settings["model"],key,settings["endpoint"],candidate)
                    votes.append({
                        "provider":provider,"model":settings["model"],
                        "approved":reply["approved"],"reason":reply["reason"],
                        "flags":list(reply["flags"]),
                        "input_tokens":reply["input_tokens"],"output_tokens":reply["output_tokens"],
                        "reserved_estimate_usd":reserved,
                    })
                except (RuntimeError,ValueError,TypeError,KeyError,OSError,OverflowError) as exc:
                    votes.append({"provider":provider,"model":settings["model"],
                                  "approved":False,"reason":str(exc)[:110],
                                  "flags":["provider_error"]})
            approvals=sum(bool(v.get("approved")) for v in votes)
            required=(config["required_approvals"] if config["mode"]=="consensus" else 1)
            success=approvals>=required and len(votes)>=required
            # In consensus mode, any configured model failure/veto prevents entry;
            # this is a conservative unanimous gate with a minimum vote threshold.
            if config["mode"]=="consensus":
                success=success and all(v.get("approved") for v in votes)
            return ReviewDecision(success,
                f"Cloud review: {approvals}/{len(votes)} approved; required {required}; "
                + ("paper entry eligible" if success else "entry vetoed"),
                "cloud-consensus" if config["mode"]=="consensus" else "cloud-single",
                () if success else ("ai_veto",),
                tuple(votes),round(estimate_total,6))
        except (OSError,ValueError,TypeError,KeyError,OverflowError) as exc:
            return ReviewDecision(False,"Cloud review blocked ("+type(exc).__name__+")",
                                  "cloud-error",("fail_closed",))
