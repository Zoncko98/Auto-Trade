"""Provider-specific OAuth companion adapter for PUBLIC financial-news research.

OAuth credentials remain on the user's own AI computer. TrueNAS sends only
symbol and public headlines to a private-LAN companion endpoint; it never
accepts ChatGPT, Google, or other account passwords or raw OAuth tokens.
"""
import ipaddress
import json
import os
import re
from urllib.parse import urlparse
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError

class OAuthAIUnavailable(RuntimeError):
    pass

ALLOWED_PROVIDERS={"chatgpt-oauth","gemini-oauth"}
def _settings(env=None):
    e=env if env is not None else os.environ
    provider=e.get("AI_PROVIDER","").strip().lower()
    if provider not in ALLOWED_PROVIDERS:
        raise OAuthAIUnavailable("Select a supported OAuth provider")
    value=e.get("OAUTH_AI_URL","").rstrip("/")
    parsed=urlparse(value)
    if parsed.scheme not in ("http","https") or not parsed.hostname or not parsed.port or parsed.path not in ("","/") or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise OAuthAIUnavailable("Invalid companion endpoint")
    try:
        host=ipaddress.ip_address(parsed.hostname)
        if not (host.is_private or host.is_loopback):
            raise OAuthAIUnavailable("OAuth companion must run on the private LAN")
    except ValueError:
        raise OAuthAIUnavailable("Use a numeric private LAN address") from None
    token=e.get("OAUTH_AI_BRIDGE_TOKEN","")
    if not (isinstance(token,str) and 24<=len(token)<=256 and re.fullmatch(r"[A-Za-z0-9._~\-]+",token)):
        raise OAuthAIUnavailable("Companion bridge token not configured")
    model=e.get("OAUTH_AI_MODEL","")
    if not (isinstance(model,str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/\-]{0,95}",model)):
        raise OAuthAIUnavailable("Invalid provider model ID")
    return provider,value,token,model

def classify_news(symbol,headline_rows,opener=urlopen):
    provider,url,token,model=_settings()
    if not (isinstance(symbol,str) and re.fullmatch(r"[A-Z]{1,8}",symbol)):
        raise OAuthAIUnavailable("Invalid ticker")
    if not (isinstance(headline_rows,list) and 1<=len(headline_rows)<=6):
        raise OAuthAIUnavailable("Timestamped public headlines required")
    rows=[]
    for row in headline_rows:
        if not isinstance(row,dict) or not all(isinstance(row.get(k),str) and 1<=len(row[k])<=300 for k in ("title","source","published_at")):
            raise OAuthAIUnavailable("Invalid public headline")
        rows.append({k:row[k] for k in ("title","source","published_at")})
    body=json.dumps({"provider":provider,"model":model,"ticker":symbol,"headlines":rows}).encode()
    req=Request(url+"/api/classify",data=body,headers={"Content-Type":"application/json","Authorization":"Bearer "+token},method="POST")
    try:
        with opener(req,timeout=35) as response:
            data=response.read(12001)
        if len(data)>12000:raise OAuthAIUnavailable("OAuth response exceeds limit")
        obj=json.loads(data)
    except (HTTPError,URLError,TimeoutError,OSError,ValueError,TypeError):
        raise OAuthAIUnavailable("OAuth companion unavailable or response invalid") from None
    try:
        if not isinstance(obj,dict) or obj.get("ticker")!=symbol or obj.get("provider")!=provider:
            raise ValueError("Provider mismatch")
        a,b=obj["sentiment"],obj["impact"]
        if type(a) is not int or a not in (-2,-1,0,1,2):raise ValueError
        if type(b) is not int or b not in (0,1,2):raise ValueError
        if not all(isinstance(obj.get(k),str) and 0<len(obj[k])<300 for k in ("catalyst","downside_risk")):raise ValueError
    except (TypeError,ValueError,KeyError):
        raise OAuthAIUnavailable("OAuth model answer failed validation") from None
    return {"ticker":symbol,"model":model,"provider":provider,
            "sentiment":a,"impact":b,"catalyst":obj["catalyst"],
            "downside_risk":obj["downside_risk"],"calibrated_win_probability":None}
