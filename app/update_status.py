"""Read local version and a host-maintained (read-only) GitHub update manifest.

The container never receives GitHub SSH keys, tokens, or Docker privileges.
"""
from __future__ import annotations
import json
import re
from pathlib import Path

VERSION_RE=re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
def semver(tag):
    if not isinstance(tag,str):return None
    match=VERSION_RE.fullmatch(tag.strip())
    return tuple(int(i) for i in match.groups()) if match else None

def installed_version(app_dir):
    path=Path(app_dir)/"VERSION"
    try:
        tag=path.read_text(encoding="utf-8").strip()
        return tag if semver(tag) else "1.0.0"
    except OSError:
        return "1.0.0"

def update_information(state_dir,app_dir):
    installed=installed_version(app_dir)
    result={"installed":installed,"latest":None,"update_available":False,
            "checked_at":None,"status":"not_checked",
            "release_url":None,"method":"Private GitHub release check via host"}
    path=Path(state_dir)/"update_status.json"
    try:
        if path.stat().st_size>8192:
            return result
        doc=json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(doc,dict) or doc.get("schema")!=1:
            return result
        latest=doc.get("latest")
        if semver(latest) is None:
            return result
        checked=doc.get("checked_at")
        if not isinstance(checked,str) or len(checked)>60:checked=None
        result.update({"latest":latest.lstrip("v"),"checked_at":checked,
                       "status":"checked","update_available":semver(latest)>semver(installed)})
        if result["update_available"]:
            result["release_url"]="https://github.com/Zoncko98/Auto-Trade/tree/v"+result["latest"]
    except (OSError,ValueError,TypeError,KeyError):
        pass
    return result

# Unified public releases use the publicly accessible GitHub tags API instead
# of a private host-generated manifest. TrueNAS, not the app container, actually
# applies the ghcr.io/.../auto-trade:stable image upgrade.
import threading
import time
from datetime import datetime,timezone
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError

_public_lock=threading.Lock()
_public_cache=None
_public_cache_time=0.0
_PUBLIC_TAGS_API="https://api.github.com/repos/Zoncko98/Auto-Trade/tags?per_page=25"
def public_update_information(app_dir,opener=urlopen):
    global _public_cache,_public_cache_time
    installed=installed_version(app_dir)
    result={"installed":installed,"latest":None,"update_available":False,
      "checked_at":None,"status":"unavailable",
      "release_url":None,"source_url":"https://github.com/Zoncko98/Auto-Trade",
      "method":"Native TrueNAS Apps update for unified public GHCR image",
      "note":"Source N/A is normal for a TrueNAS custom YAML app; image digest checks provide native update alerts."}
    with _public_lock:
        now=time.monotonic()
        if _public_cache is None or now-_public_cache_time>600:
            try:
                req=Request(_PUBLIC_TAGS_API,headers={
                  "Accept":"application/vnd.github+json",
                  "User-Agent":"AutoTrader-Public-Release-Check"})
                with opener(req,timeout=5) as response:
                    raw=response.read(24001)
                if len(raw)>24000:raise ValueError("GitHub response too large")
                data=json.loads(raw)
                if not isinstance(data,list):raise ValueError("Invalid GitHub response")
                tags=[str(item.get("name","")) for item in data
                    if isinstance(item,dict) and semver(item.get("name"))]
                latest=max(tags,key=semver) if tags else None
                _public_cache=latest
                _public_cache_time=now
            except (URLError,HTTPError,TimeoutError,OSError,ValueError,TypeError):
                _public_cache_time=now
                return result
        latest=_public_cache
    if latest and semver(latest):
        result["latest"]=latest.lstrip("v")
        result["update_available"]=semver(latest)>semver(installed)
        result["status"]="checked"
        result["checked_at"]=datetime.now(timezone.utc).isoformat(timespec="seconds")
        if result["update_available"]:
            result["release_url"]="https://github.com/Zoncko98/Auto-Trade/tree/"+latest
    return result
