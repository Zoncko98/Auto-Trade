"""Persistent one-app setup, credential protection, and provider validation."""
from __future__ import annotations
import hmac, ipaddress, json, os, re, secrets, tempfile
from pathlib import Path
from urllib.parse import urlparse
from profile_auth import rotate as set_initial_password, revision as profile_revision, validate_new_password

PUBLIC_FIELDS=("ai_provider","ollama_url","ai_model","oauth_bridge_url",
               "oauth_model","schwab_app_key","schwab_callback_url",
               "paper_enabled","market_enabled","paper_capital","forecast_url",
               "forecast_mode","forecast_ai_review")
SECRET_FIELDS=("schwab_app_secret","oauth_bridge_token")
PROVIDERS=("ollama","chatgpt-oauth","gemini-oauth","none")
MODELS_RE=re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,95}$")
DEFAULTS={"ai_provider":"ollama","ollama_url":"","ai_model":"qwen3.5:4b",
          "oauth_bridge_url":"","oauth_model":"","schwab_app_key":"",
          "schwab_callback_url":"https://127.0.0.1:8182",
          "paper_enabled":False,"market_enabled":False,"paper_capital":100.0,
          "forecast_url":"","forecast_mode":"auto","forecast_ai_review":False,
          "live_enabled":False,"live_confirmed":False,
          "live_account_hash":""}

class SetupError(ValueError): pass

def _path(state, name):
    return Path(state)/"config"/name

def atomic_save(path, document):
    path=Path(path)
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(dir=path.parent,prefix=".settings-")
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            os.fchmod(f.fileno(),0o600)
            json.dump(document,f,sort_keys=True,allow_nan=False)
            f.flush();os.fsync(f.fileno())
        os.replace(name,path)
        os.chmod(path,0o600)
    finally:
        if os.path.exists(name):os.unlink(name)

def _load(path):
    try:
        p=Path(path)
        if not p.is_file() or not 0<p.stat().st_size<=8192:return {}
        obj=json.loads(p.read_text(encoding="utf-8"))
        return obj if isinstance(obj,dict) else {}
    except (OSError,ValueError,TypeError):
        return {}

def username(state):
    profile=_load(Path(state)/"profile_user.json")
    candidate=profile.get("username","Administrator")
    return candidate if isinstance(candidate,str) and re.fullmatch(r"[A-Za-z0-9._-]{3,32}",candidate) else "Administrator"

def configured(state):
    return (_path(state,"integrations.json").is_file() and
            profile_revision(state)>0)

def pairing_code(state):
    if configured(state):return None
    target=Path(state)/".setup_code"
    if target.exists():
        if target.stat().st_mode & 0o077:raise SetupError("Insecure setup token permissions")
        return target.read_text(encoding="ascii").strip()
    code=secrets.token_hex(12)
    # Open with O_EXCL so a second startup cannot silently rotate the code.
    try:
        fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    except FileExistsError:
        return target.read_text(encoding="ascii").strip()
    with os.fdopen(fd,"w",encoding="ascii") as f:f.write(code)
    return code

def private_url(value):
    if not isinstance(value,str) or len(value)>180:raise SetupError("Invalid LAN endpoint")
    parsed=urlparse(value)
    if (parsed.scheme not in ("http","https") or not parsed.hostname or
        parsed.username or parsed.password or parsed.path not in ("","/") or
        parsed.query or parsed.fragment or parsed.port is None):
        raise SetupError("Enter http(s)://private-LAN-IP:port")
    try:
        ip=ipaddress.ip_address(parsed.hostname)
    except ValueError:
        raise SetupError("Use a numeric private-network address") from None
    if not (ip.is_private or ip.is_loopback):
        raise SetupError("Only private/LAN AI hosts are accepted")
    return value.rstrip("/")

def settings(state):
    saved=_load(_path(state,"integrations.json"))
    return {**DEFAULTS,**{k:v for k,v in saved.items() if k in DEFAULTS}}

def credentials(state):
    return _load(_path(state,"credentials.json"))

def public_summary(state):
    d=settings(state)
    secrets_doc=credentials(state)
    exposed={k:v for k,v in d.items() if k not in ("live_account_hash","live_confirmed")}
    return {**exposed,"live_account_selected":bool(d.get("live_account_hash")),
            "setup_complete":configured(state),
            "setup_status":{
              "administrator":"complete" if profile_revision(state)>0 else "pending",
              "ai":"configured" if d["ai_provider"]!="none" else "optional",
              "schwab_developer":"configured" if d["schwab_app_key"] and secrets_doc.get("schwab_app_secret") else "optional",
              "schwab_account":"connected" if (Path(state)/"schwab_token.json").is_file() else "not_connected",
              "paper":"enabled" if d["paper_enabled"] else "off",
              "market_quotes":"enabled" if d["market_enabled"] else "off",
              "live":"enabled" if d.get("live_enabled") else "off"
            },
            "schwab_secret_set":bool(secrets_doc.get("schwab_app_secret")),
            "oauth_bridge_token_set":bool(secrets_doc.get("oauth_bridge_token")),
            "schwab_token_connected":(Path(state)/"schwab_token.json").is_file(),
            "live_enabled":bool(d.get("live_enabled",False))}

def validate(payload,current,old_secrets):
    if not isinstance(payload,dict):raise SetupError("Expected setup object")
    allowed=set(PUBLIC_FIELDS)|set(SECRET_FIELDS)
    if set(payload)-allowed:raise SetupError("Unsupported installation setting")
    result=dict(current)
    secrets_doc=dict(old_secrets)
    for k in PUBLIC_FIELDS:
        if k in payload:result[k]=payload[k]
    for key in SECRET_FIELDS:
        if key in payload and payload[key] not in ("",None):
            value=payload[key]
            if not isinstance(value,str) or not 10<=len(value)<=256 or any(ord(ch)<32 for ch in value):
                raise SetupError("Invalid secret format")
            secrets_doc[key]=value
    if result["ai_provider"] not in PROVIDERS:raise SetupError("Unsupported AI provider")
    if result["forecast_mode"] not in ("auto","built_in","advanced"):
        raise SetupError("Select automatic, built-in, or advanced forecasting")
    if result["ollama_url"]:result["ollama_url"]=private_url(result["ollama_url"])
    if result["oauth_bridge_url"]:result["oauth_bridge_url"]=private_url(result["oauth_bridge_url"])
    if result["forecast_url"]:result["forecast_url"]=private_url(result["forecast_url"])
    if not (isinstance(result["ai_model"],str) and MODELS_RE.fullmatch(result["ai_model"])):
        raise SetupError("Invalid Ollama model")
    if result["oauth_model"] and not (isinstance(result["oauth_model"],str) and MODELS_RE.fullmatch(result["oauth_model"])):
        raise SetupError("Invalid OAuth model")
    key=result["schwab_app_key"]
    if not isinstance(key,str) or len(key)>256 or any(ord(ch)<33 for ch in key):
        raise SetupError("Invalid Schwab developer app key")
    callback=urlparse(result["schwab_callback_url"])
    if (callback.scheme!="https" or not (1024 <= (callback.port or 0) <=65535)
        or callback.fragment or callback.username or callback.password
        or callback.query or not callback.hostname):
        raise SetupError("Use your exact registered HTTPS Schwab callback URL")
    if callback.hostname=="127.0.0.1":
        if callback.path not in ("","/"):
            raise SetupError("Loopback callback must match the registered URL (usually no path)")
    else:
        try:
            host=ipaddress.ip_address(callback.hostname)
            permitted=host.is_private and not host.is_loopback and not host.is_link_local
        except ValueError:
            permitted=False
        if not permitted or callback.path!="/schwab/callback":
            raise SetupError("For an automatic callback use https://PRIVATE_NAS_IP:PORT/schwab/callback, registered exactly at Schwab")
    for key in ("paper_enabled","market_enabled","forecast_ai_review"):
        if type(result[key]) is not bool:raise SetupError("Invalid service enable option")
    if type(result["paper_capital"]) not in (float,int) or not 1<=result["paper_capital"]<=100000:
        raise SetupError("Invalid paper trading capital")
    if result["ai_provider"]=="ollama" and not result["ollama_url"]:
        raise SetupError("Ollama requires a private LAN URL; or select AI disabled")
    if result["ai_provider"] in ("chatgpt-oauth","gemini-oauth"):
        if not result["oauth_bridge_url"] or not result["oauth_model"] or len(secrets_doc.get("oauth_bridge_token",""))<24:
            raise SetupError("OAuth companion URL, authorized model and 24+ character bridge token required")
    # A checked read-only market monitor waits for Schwab OAuth credentials;
    # do not block installation just because brokerage sign-in comes later.
    selected=result.get("live_account_hash","")
    if not isinstance(selected,str) or (selected and not re.fullmatch(r"[A-Za-z0-9_-]{5,150}",selected)):
        raise SetupError("Invalid Schwab account selection")
    return result,secrets_doc

def save(state,payload):
    new,sec=validate(payload,settings(state),credentials(state))
    atomic_save(_path(state,"credentials.json"),sec)
    atomic_save(_path(state,"integrations.json"),new)
    # Compatibility for the schwab-py client used by the read-only collector.
    if new["schwab_app_key"] and sec.get("schwab_app_secret"):
        env_doc=("SCHWAB_APP_KEY="+new["schwab_app_key"]+"\n"+
                 "SCHWAB_APP_SECRET="+sec["schwab_app_secret"]+"\n"+
                 "SCHWAB_CALLBACK_URL="+new["schwab_callback_url"]+"\n")
        if "\n" in new["schwab_app_key"] or "\n" in sec["schwab_app_secret"]:
            raise SetupError("Invalid Schwab credential")
        dest=_path(state,"schwab.env")
        fd,temp=tempfile.mkstemp(dir=dest.parent,prefix=".schwab-env-")
        try:
            with os.fdopen(fd,"w",encoding="utf-8") as stream:
                os.fchmod(stream.fileno(),0o600)
                stream.write(env_doc);stream.flush();os.fsync(stream.fileno())
            os.replace(temp,dest)
        finally:
            if os.path.exists(temp):os.unlink(temp)
    return public_summary(state)

def initialize(state,code,password,options,bootstrap_password,admin_username="Administrator"):
    if configured(state) or profile_revision(state)>0:
        raise SetupError("This installation has already been claimed")
    expected=pairing_code(state)
    if not isinstance(code,str) or not hmac.compare_digest(code,expected):
        raise SetupError("Incorrect one-time pairing code")
    validate_new_password(password)
    if not isinstance(admin_username,str) or not re.fullmatch(r"[A-Za-z0-9._-]{3,32}",admin_username):
        raise SetupError("Username must be 3–32 letters, numbers, dots, underscores or hyphens")
    # Validate before writing the permanent first-user profile.
    validate(options,settings(state),credentials(state))
    save(state,options)
    atomic_save(Path(state)/"profile_user.json",{"username":admin_username})
    set_initial_password(state,bootstrap_password,password,bootstrap_password)
    (Path(state)/".setup_code").unlink(missing_ok=True)
    return public_summary(state)
