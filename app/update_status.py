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
