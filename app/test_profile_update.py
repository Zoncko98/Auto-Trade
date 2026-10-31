"""End-to-end HTTPS account security and private release notification regression."""
import http.client
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import unittest

APP=Path(__file__).resolve().parent
ORIGINAL="bootstrap-application-pass-123456"
CHANGED="correct-horse-battery-very-new-123456"

class ProfileTests(unittest.TestCase):
    def test_password_rotation_revokes_all_sessions_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            state=root/"state";state.mkdir()
            c=root/"cert.pem";key=root/"key.pem"
            p=subprocess.run(["openssl","req","-x509","-newkey","ec",
                "-pkeyopt","ec_paramgen_curve:prime256v1","-nodes",
                "-keyout",str(key),"-out",str(c),"-days","1","-subj","/CN=localhost"],
                text=True,capture_output=True,timeout=15)
            self.assertEqual(p.returncode,0,p.stderr)
            with socket.socket() as s:
                s.bind(("127.0.0.1",0))
                port=s.getsockname()[1]
            env=dict(os.environ,DASHBOARD_PASSWORD=ORIGINAL,
              DASHBOARD_SESSION_SECRET="long-synthetic-session-key-test-123456789012345678",
              DASHBOARD_TLS_CERT=str(c),DASHBOARD_TLS_KEY=str(key),
              DASHBOARD_BIND="127.0.0.1",DASHBOARD_PORT=str(port),STATE_DIR=str(state))
            context=ssl._create_unverified_context()
            def start():
                srv=subprocess.Popen([sys.executable,"-u","dashboard_server.py"],
                    cwd=APP,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
                for i in range(60):
                    if srv.poll() is not None:
                        self.fail("Server terminated "+srv.stderr.read().decode()[-500:])
                    try:
                        status,body,cookie=call("GET","/health")
                        if status==200:return srv
                    except (OSError,ssl.SSLError):
                        time.sleep(0.1)
                self.fail("HTTPS server not listening")
            def call(method,path,payload=None,cookie=None,csrf=None):
                conn=http.client.HTTPSConnection("127.0.0.1",port,context=context,timeout=4)
                headers={"Origin":f"https://127.0.0.1:{port}"}
                if payload is not None:headers["Content-Type"]="application/json"
                if cookie:headers["Cookie"]=cookie
                if csrf:headers["X-CSRF-Token"]=csrf
                conn.request(method,path,json.dumps(payload) if payload is not None else None,headers)
                response=conn.getresponse()
                output=json.loads(response.read())
                result=(response.status,output,response.getheader("Set-Cookie",""))
                conn.close()
                return result
            def stop(srv):
                srv.terminate()
                try:srv.communicate(timeout=5)
                except subprocess.TimeoutExpired:srv.kill();srv.wait(timeout=3)
            srv=start()
            try:
                code,session,session_cookie=call("POST","/api/login",{"password":ORIGINAL})
                self.assertEqual(code,200)
                cookie=session_cookie.split(";",1)[0]
                token=session["csrf"]
                status,profile,_=call("GET","/api/profile",cookie=cookie)
                self.assertEqual(status,200);self.assertTrue(profile["password_change_enabled"])
                self.assertEqual(profile["version"],"1.0.9")
                bad,_,_=call("POST","/api/profile/password",
                    {"current_password":"bad","new_password":CHANGED},cookie,token)
                self.assertEqual(bad,400)
                status,_,_=call("GET","/api/profile",cookie=cookie)
                self.assertEqual(status,200)
                success,data,expiry_cookie=call("POST","/api/profile/password",
                    {"current_password":ORIGINAL,"new_password":CHANGED},cookie,token)
                self.assertEqual(success,200)
                self.assertIn("Max-Age=0",expiry_cookie)
                self.assertNotIn("password",str(data).lower().replace("password changed",""))
                auth_file=state/"profile_auth.json"
                self.assertEqual(auth_file.stat().st_mode & 0o777,0o600)
                self.assertNotIn(CHANGED,auth_file.read_text())
                self.assertNotIn(ORIGINAL,auth_file.read_text())
                status,_,_=call("GET","/api/profile",cookie=cookie)
                self.assertEqual(status,401)
                status,_,_=call("POST","/api/login",{"password":ORIGINAL})
                self.assertEqual(status,401)
                status,good,new_cookie=call("POST","/api/login",{"password":CHANGED})
                self.assertEqual(status,200)
                cookie2=new_cookie.split(";",1)[0]
                status,_,_=call("GET","/api/profile",cookie=cookie2)
                self.assertEqual(status,200)
                (state/"update_status.json").write_text(json.dumps(
                    {"schema":1,"latest":"1.0.10","checked_at":"2026-10-31T05:00:00Z"}))
                status,up,_=call("GET","/api/update",cookie=cookie2)
                self.assertEqual(status,200)
                self.assertEqual(up["installed"],"1.0.9")
                self.assertTrue(up["update_available"])
                self.assertEqual(up["latest"],"1.0.10")
            finally:stop(srv)
            srv=start()
            try:
                status,_,_=call("POST","/api/login",{"password":ORIGINAL})
                self.assertEqual(status,401)
                status,_,_=call("POST","/api/login",{"password":CHANGED})
                self.assertEqual(status,200)
            finally:stop(srv)

if __name__=="__main__":unittest.main()
