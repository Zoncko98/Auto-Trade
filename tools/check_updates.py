"""TrueNAS HOST-SIDE private GitHub release checker.

Run from TrueNAS Cron as a trusted host account. The dashboard only reads the
resulting JSON file; no GitHub credentials/SSH keys are mounted in containers.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile

RELEASE_RE=re.compile(r"^refs/tags/v([0-9]+)\.([0-9]+)\.([0-9]+)$")

def latest_release(ls_remote_output):
    versions=[]
    for line in ls_remote_output.splitlines():
        fields=line.strip().split()
        if len(fields)!=2:continue
        match=RELEASE_RE.fullmatch(fields[1])
        if match:
            versions.append(tuple(int(x) for x in match.groups()))
    if not versions:return None
    return ".".join(str(x) for x in max(versions))

def check(repo,state_dir,key=None):
    remote=repo if repo=="git@github.com:Zoncko98/Auto-Trade.git" else None
    if remote is None:
        repo=Path(repo).expanduser().resolve()
        if not (repo/".git").exists():
            raise ValueError("Local Git clone not found")
        remote="origin"
    state_dir=Path(state_dir).expanduser().resolve()
    env=dict(os.environ)
    if key:
        key=Path(key).expanduser().resolve()
        if not key.is_file():raise ValueError("Private deploy SSH key missing")
        hostkeys=key.parent/"known_hosts"
        if not hostkeys.is_file():raise ValueError("Known SSH host keys file missing")
        env["GIT_SSH_COMMAND"]=("ssh -i "+shlex.quote(str(key))+
          " -o UserKnownHostsFile="+shlex.quote(str(hostkeys))+
          " -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes")
    args=["git","ls-remote","--refs","--tags",remote]
    if remote=="origin":
        args=["git","-c",f"safe.directory={repo}","ls-remote","--refs","--tags",remote]
    p=subprocess.run(args,cwd=repo if remote=="origin" else None,
        env=env,capture_output=True,text=True,timeout=25,check=True)
    latest=latest_release(p.stdout)
    if latest is None:raise ValueError("No stable version tags in remote")
    doc={"schema":1,"latest":latest,"checked_at":datetime.now(timezone.utc).isoformat()}
    state_dir.mkdir(parents=True,exist_ok=True)
    fd,path=tempfile.mkstemp(dir=state_dir,prefix=".update-")
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            os.fchmod(f.fileno(),0o600)
            json.dump(doc,f,sort_keys=True)
            f.flush();os.fsync(f.fileno())
        os.replace(path,state_dir/"update_status.json")
        os.chmod(state_dir/"update_status.json",0o600)
    finally:
        if os.path.exists(path):os.unlink(path)
    return doc

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo",required=True,help="Host checkout of private Auto-Trade Git repository")
    parser.add_argument("--state-dir",required=True,help="Host app state dir mounted inside the dashboard")
    parser.add_argument("--ssh-key",help="Read-only/restricted GitHub SSH deploy key on host; never mount in app")
    args=parser.parse_args()
    print(json.dumps(check(args.repo,args.state_dir,args.ssh_key),sort_keys=True))
