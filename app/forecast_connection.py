"""Read-only forecast discovery and connectivity diagnostics.

The optional forecast service is NOT the Ollama /api/generate endpoint.
An explicit forecast_url overrides discovery. If the user runs Ollama on a
private-LAN computer, Auto Trader can look for its research companion there
at the documented port 8766. No broker secrets or trading privileges.
"""
from __future__ import annotations
from datetime import datetime,timezone
from urllib.parse import urlparse
from urllib.request import Request,urlopen,build_opener,HTTPRedirectHandler
from urllib.error import HTTPError,URLError
from ipaddress import ip_address
import json,math,os

MAX_BYTES=350000
class ForecastConnectionError(ValueError):pass

class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        raise ForecastConnectionError("Forecast endpoint attempted to redirect unexpectedly")

def validate_url(url):
    if not isinstance(url,str) or not url or len(url)>190:raise ForecastConnectionError("Enter a forecast service address")
    p=urlparse(url)
    if p.scheme not in ("http","https") or not p.hostname or p.port is None or not 1<=p.port<=65535:
        raise ForecastConnectionError("Use http://PRIVATE_AI_IP:8766")
    if p.path not in ("","/") or p.params or p.query or p.fragment or p.username or p.password:
        raise ForecastConnectionError("Use only the forecast host and port")
    try:
        h=ip_address(p.hostname)
    except ValueError:
        raise ForecastConnectionError("Use a numeric private LAN IP") from None
    if not (h.is_private or h.is_loopback) or h.is_link_local or h.is_multicast or h.is_unspecified:
        raise ForecastConnectionError("Forecast endpoints must use a private LAN IP")
    return url.rstrip("/")

def resolve_url(saved):
    direct=saved.get("forecast_url","")
    if direct:
        return validate_url(direct),"manual"
    ai=saved.get("ollama_url","")
    if saved.get("ai_provider")=="ollama" and ai:
        origin=validate_url(ai)
        parsed=urlparse(origin)
        return validate_url(parsed.scheme+"://"+parsed.hostname+":8766"),"ollama-host-autodiscovery"
    return None,"not_configured"

def fetch(base,route,opener=None,timeout=7):
    url=validate_url(base)
    if route not in ("/health","/api/forecast","/api/models"):
        raise ForecastConnectionError("Unsupported research endpoint")
    opener=opener or build_opener(NoRedirects()).open
    req=Request(url+route,headers={"Accept":"application/json","User-Agent":"AutoTrader-Research-Probe"})
    try:
        with opener(req,timeout=timeout) as res:
            if getattr(res,"status",200)!=200:raise ForecastConnectionError("Research service did not return HTTP 200")
            raw=res.read(MAX_BYTES+1)
        if len(raw)>MAX_BYTES:raise ForecastConnectionError("Forecast response exceeds size limit")
        data=json.loads(raw)
        if not isinstance(data,dict):raise ValueError
        return data
    except ForecastConnectionError:raise
    except (HTTPError,URLError,TimeoutError,ConnectionError,OSError,ValueError,TypeError) as err:
        raise ForecastConnectionError("Cannot contact research service on this host and port") from None

def probe(base,opener=None):
    info=fetch(base,"/health",opener)
    state=info.get("status")
    if not isinstance(state,dict) or info.get("mode")!="research_only":
        raise ForecastConnectionError("Endpoint is reachable, but it is not an Auto Trader research service")
    phase=state.get("phase","unknown")
    if not isinstance(phase,str) or len(phase)>60:phase="unknown"
    result={"connected":True,"phase":phase,"research_only":True,"service_url":validate_url(base),
            "last_refresh":state.get("last_refresh") if isinstance(state.get("last_refresh"),str) else None}
    if phase=="error":result["message"]="Research engine reported a refresh error; open its local logs"
    elif phase=="ready":result["message"]="Forecast research service is ready"
    else:result["message"]="Service is reachable; model research is still preparing"
    return result

def connection_status(saved,opener=None):
    base,mode=resolve_url(saved)
    if not base:
        return {"connected":False,"source":mode,"service_url":None,
                "message":"Enter a forecast service URL or connect an Ollama computer running the research companion"}
    try:
        return {**probe(base,opener),"source":mode}
    except ForecastConnectionError as ex:
        return {"connected":False,"source":mode,"service_url":base,
                "message":str(ex)}

def research_doc(saved,route,opener=None):
    base,mode=resolve_url(saved)
    if not base:
        raise ForecastConnectionError("Forecast not connected. Open Profile → Integrations, configure your AI workstation, and test the research connection.")
    doc=fetch(base,route,opener)
    if route=="/api/forecast":
        if not isinstance(doc.get("candidates"),list):
            # Service may be warming model weights or gathering stock data.
            if doc.get("status")=="pending":return doc
            raise ForecastConnectionError("Research service returned an incomplete forecast")
        if len(doc["candidates"])>25:raise ForecastConnectionError("Invalid candidate count")
    return doc
