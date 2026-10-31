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
