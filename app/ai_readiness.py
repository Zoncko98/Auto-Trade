"""Read-only AI compatibility summary. Never changes trading permissions."""
import re

def model_size_billions(name):
    if not isinstance(name,str):return None
    match=re.search(r"(?<![A-Za-z0-9])([0-9]+(?:\.[0-9]+)?)b(?![A-Za-z0-9])",name,re.I)
    return float(match.group(1)) if match else None

def summary(config):
    provider=str(config.get("ai_provider") or "none")
    model=str(config.get("ai_model") or "")
    if provider=="ollama":
        size=model_size_billions(model)
        meets=size is not None and size>=4
        return {"provider":"ollama","model":model,"parameter_billions_from_name":size,
                "minimum_local_billions":4,"size_claim_meets_minimum":meets,
                "status":"needs_runtime_verification" if meets else "unverified_or_below_minimum",
                "connection_tested":False,"capability_tested":False,
                "trading_enforcement_active":False,
                "note":"Model name is not authoritative; verify Ollama metadata and capabilities before enforcement."}
    if provider in ("chatgpt-oauth","gemini-oauth"):
        return {"provider":provider,"model":model,"status":"needs_runtime_verification",
                "connection_tested":False,"capability_tested":False,
                "trading_enforcement_active":False,"note":"Cloud provider selected; credentials and capability not tested by this endpoint."}
    return {"provider":provider,"status":"not_configured","connection_tested":False,
            "capability_tested":False,"trading_enforcement_active":False}


def effective_selected_model(config, state_dir):
    """Report the same selected news model that local_ai_gateway will use.

    A stored shared selection overrides the integration default. Invalid
    selection data must not be misrepresented as a functioning fallback.
    """
    import json
    from pathlib import Path
    provider=config.get("ai_provider")
    if provider!="ollama":
        return config.get("oauth_model","") if provider in ("chatgpt-oauth","gemini-oauth") else ""
    fallback=config.get("ai_model","")
    selection=Path(state_dir)/"live"/"model_selection.json"
    try:
        if not selection.exists():
            return fallback
        if not 0 < selection.stat().st_size <= 512:
            return ""
        record=json.loads(selection.read_text(encoding="utf-8"))
        model=record.get("model") if isinstance(record,dict) and record.get("version")==1 else None
        if not isinstance(model,str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,95}",model):
            return ""
        return model
    except (OSError,ValueError,TypeError,UnicodeError):
        return ""


def verify_ollama_model(base, model, opener=None):
    """Check installed Ollama model metadata via bounded /api/tags, without inference.

    /api/show can include hundreds of KB of templates and sometimes exceeds
    a small readiness payload limit, falsely reporting a healthy model offline.
    """
    import json
    from urllib.request import Request, urlopen
    from unified_config import private_url
    if not isinstance(model,str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,95}",model):
        return {"status":"invalid_model","connection_tested":False,"capability_tested":False}
    try:
        endpoint=private_url(base)
        request=Request(endpoint+"/api/tags",headers={"Accept":"application/json"},method="GET")
        with (opener or urlopen)(request,timeout=5) as response:
            data=response.read(131073)
        if len(data)>131072:raise ValueError("response size")
        doc=json.loads(data)
        catalog=doc.get("models")
        if not isinstance(catalog,list):raise ValueError("invalid model catalog")
        matches=[x for x in catalog if isinstance(x,dict)
                 and (x.get("name")==model or x.get("model")==model)]
        if len(matches)!=1:raise ValueError("selected model missing or ambiguous")
        details=matches[0].get("details",{})
        if not isinstance(details,dict):raise ValueError("model metadata missing")
        raw=details.get("parameter_size")
        if not isinstance(raw,str):raise ValueError("parameter size missing")
        match=re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*([BM])\s*",raw,re.I)
        if not match:raise ValueError("unrecognized model size")
        size=float(match.group(1))*(1 if match.group(2).upper()=="B" else .001)
        return {"status":"metadata_verified" if size>=4 else "below_minimum",
                "provider":"ollama","model":model,"verified_parameter_billions":size,
                "connection_tested":True,"capability_tested":False,
                "meets_minimum":size>=4,"trading_enforcement_active":False,
                "note":"Installed-model metadata verified; inference capability still untested."}
    except Exception:
        return {"status":"unavailable_or_invalid_metadata","provider":"ollama","model":model,
                "connection_tested":False,"capability_tested":False,
                "meets_minimum":False,"trading_enforcement_active":False}
