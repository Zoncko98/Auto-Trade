"""Authenticated cloud-provider control endpoints for the PaperPilot dashboard.

Secrets are written on the server with file mode 0600 and are never included
in GET responses, HTML, browser storage, trade logs or application logs.
"""
import fcntl
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from cloud_models import (
    PROVIDER_IDS, CloudReviewRouter, _model_request, default_cloud_config,
    read_cloud_config, read_cloud_keys, set_cloud_key, validate_cloud_config,
)
from dashboard_control import now_utc, write_atomic

_cloud_lock = threading.Lock()


def _usage_today(path):
    calls=0
    cost=0.0
    date=datetime.now(timezone.utc).date().isoformat()
    if path.exists():
        if path.stat().st_size>5_000_000:
            raise ValueError("Usage file too large")
        for line in path.read_text(encoding="utf-8").splitlines():
            record=json.loads(line)
            if record.get("date")==date:
                calls+=1
                cost+=float(record.get("reserved_estimate_usd",0))
    return {"calls":calls,"reserved_estimate_usd":round(cost,6),
            "note":"Conservative request estimates, not an actual provider invoice"}


class CloudEndpoints:
    def cloud_get(self, state_dir: Path):
        try:
            config=read_cloud_config(state_dir/"cloud_config.json")
            keys=read_cloud_keys(state_dir/"cloud_keys.json")
            return self._json(200,{
                "config":config,
                "credentials":{p:bool(keys.get(p)) for p in PROVIDER_IDS},
                "usage_today":_usage_today(state_dir/"cloud_usage.jsonl"),
                "paper_only":True,
            })
        except (ValueError,OSError,TypeError,KeyError):
            return self._json(500,{"error":"Cloud configuration unavailable; no orders permitted"})

    def cloud_post(self, path: str, state_dir: Path):
        # The caller checks the authenticated session, CSRF token and origin.
        try:
            data=self._body()
            if path=="/api/cloud/config":
                revision=data.get("revision")
                if type(revision) is not int:
                    raise ValueError("Expected cloud revision")
                incoming=data.get("config")
                if not isinstance(incoming,dict):
                    raise ValueError("Expected cloud configuration")
                with _cloud_lock:
                    lock_file=state_dir/"cloud_config.lock"
                    with lock_file.open("a+") as locked:
                        fcntl.flock(locked,fcntl.LOCK_EX)
                        try:
                            current=read_cloud_config(state_dir/"cloud_config.json")
                            if current["revision"]!=revision:
                                return self._json(409,{"error":"Cloud settings changed; refresh"})
                            proposal=dict(incoming)
                            proposal["revision"]=revision+1
                            proposal["updated_at"]=now_utc()
                            validated=validate_cloud_config(proposal)
                            write_atomic(state_dir/"cloud_config.json",validated)
                            with (state_dir/"settings_audit.jsonl").open("a",encoding="utf-8") as stream:
                                stream.write(json.dumps({
                                    "timestamp":now_utc(),"action":"cloud_settings_change",
                                    "revision":validated["revision"],
                                    "cloud_enabled":validated["enabled"],
                                    "mode":validated["mode"],
                                    "providers_enabled":[p for p in PROVIDER_IDS
                                        if validated["providers"][p]["enabled"]],
                                })+"\n")
                                stream.flush()
                        finally:
                            fcntl.flock(locked,fcntl.LOCK_UN)
                return self._json(200,{"config":validated,"saved":True})

            if path=="/api/cloud/key":
                provider=data.get("provider")
                if provider not in PROVIDER_IDS:
                    raise ValueError("Unrecognized provider")
                remove=data.get("remove") is True
                key=None if remove else data.get("key")
                if not remove and not isinstance(key,str):
                    raise ValueError("Key must be supplied")
                with _cloud_lock:
                    lock_file=state_dir/"cloud_config.lock"
                    with lock_file.open("a+") as locked:
                        fcntl.flock(locked,fcntl.LOCK_EX)
                        try:
                            connected=set_cloud_key(state_dir/"cloud_keys.json",provider,key)
                            with (state_dir/"settings_audit.jsonl").open("a",encoding="utf-8") as stream:
                                stream.write(json.dumps({
                                    "timestamp":now_utc(),"action":"cloud_credential_change",
                                    "provider":provider,"connected":connected,
                                })+"\n")
                        finally:
                            fcntl.flock(locked,fcntl.LOCK_UN)
                return self._json(200,{"provider":provider,"connected":connected})

            if path=="/api/cloud/test":
                provider=data.get("provider")
                if provider not in PROVIDER_IDS:
                    raise ValueError("Unrecognized provider")
                config=read_cloud_config(state_dir/"cloud_config.json")
                setting=config["providers"][provider]
                if not setting["model"]:
                    raise ValueError("Set provider model first")
                if setting["input_usd_per_million"]<=0 or setting["output_usd_per_million"]<=0:
                    raise ValueError("Set correct token rates first")
                key=read_cloud_keys(state_dir/"cloud_keys.json").get(provider)
                if not key:
                    raise ValueError("Connect an API key first")
                # A real inference test may incur a charge; the user explicitly
                # clicks this control. Respect the same daily request quota.
                router=CloudReviewRouter(state_dir)
                router._reserve(provider,config,setting)
                candidate={"trade_type":"PAPER_BUY","symbol":"TEST",
                    "price":10.0,"quantity":1.0,"timestamp_utc":now_utc(),
                    "signal":"integration_test_only","last_prices":[9,9.1,9.2,9.3,10]}
                outcome=_model_request(provider,setting["model"],key,setting["endpoint"],candidate)
                return self._json(200,{
                    "connected":True,"provider":provider,"model":setting["model"],
                    "sample_decision":"APPROVE" if outcome["approved"] else "REJECT",
                    "reason":outcome["reason"],
                    "input_tokens":outcome["input_tokens"],
                    "output_tokens":outcome["output_tokens"],
                    "note":"Synthetic integration test only; no order submitted. Provider may bill inference.",
                })
            return self._json(404,{"error":"Unknown cloud endpoint"})
        except (ValueError,TypeError,KeyError,OSError) as exc:
            # Do not disclose secrets or provider response payloads.
            return self._json(400,{"error":str(exc)[:150]})
        except RuntimeError as exc:
            return self._json(502,{"error":str(exc)[:140]})
