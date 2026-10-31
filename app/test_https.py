"""Actual HTTPS process test using a temporary self-signed certificate."""
import http.client
import json
import os
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from dashboard_control import default_control, write_atomic


class SecureServerTests(unittest.TestCase):
    def test_https_login_and_control_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            state=root/"state"
            state.mkdir()
            write_atomic(state/"control.json",default_control())
            cert=root/"cert.pem"
            key=root/"key.pem"
            openssl=subprocess.run([
                "openssl","req","-x509","-newkey","ec",
                "-pkeyopt","ec_paramgen_curve:prime256v1","-nodes",
                "-keyout",str(key),"-out",str(cert),"-days","1",
                "-subj","/CN=localhost",
                "-addext","subjectAltName=DNS:localhost,IP:127.0.0.1"
            ],capture_output=True,text=True,timeout=15)
            self.assertEqual(openssl.returncode,0,openssl.stderr)
            with socket.socket() as sock:
                sock.bind(("127.0.0.1",0))
                port=sock.getsockname()[1]
            env=os.environ.copy()
            env.update({
                "DASHBOARD_PASSWORD":"test-https-password-long-12345",
                "DASHBOARD_SESSION_SECRET":"test-https-secret-and-hmac-key-1234567890",
                "PAPER_INITIAL_CAPITAL":"100",
                "DASHBOARD_TLS_CERT":str(cert),
                "DASHBOARD_TLS_KEY":str(key),
                "DASHBOARD_BIND":"127.0.0.1",
                "DASHBOARD_PORT":str(port),
                "STATE_DIR":str(state),
            })
            server=subprocess.Popen([sys.executable,"dashboard_server.py"],
                                     cwd=Path(__file__).parent,
                                     stdout=subprocess.DEVNULL,
                                     stderr=subprocess.PIPE,env=env)
            ctx=ssl._create_unverified_context()
            try:
                for i in range(40):
                    if server.poll() is not None:
                        self.fail("HTTPS server terminated unexpectedly")
                    try:
                        conn=http.client.HTTPSConnection("127.0.0.1",port,context=ctx,timeout=2)
                        conn.request("GET","/health")
                        response=conn.getresponse()
                        payload=json.loads(response.read())
                        conn.close()
                        if response.status==200:
                            break
                    except (OSError, ssl.SSLError):
                        time.sleep(0.1)
                else:
                    self.fail("HTTPS health check unavailable")

                def call(method,path,body=None,cookie=None,csrf=None):
                    headers={"Origin":f"https://127.0.0.1:{port}"}
                    if body is not None:
                        headers["Content-Type"]="application/json"
                    if cookie:headers["Cookie"]=cookie
                    if csrf:headers["X-CSRF-Token"]=csrf
                    conn=http.client.HTTPSConnection("127.0.0.1",port,context=ctx,timeout=3)
                    conn.request(method,path,
                                 json.dumps(body) if body is not None else None,headers)
                    reply=conn.getresponse()
                    code=reply.status
                    data=json.loads(reply.read())
                    set_cookie=reply.getheader("Set-Cookie","")
                    conn.close()
                    return code,data,set_cookie

                code,login,cookie=call("POST","/api/login",{
                    "password":"test-https-password-long-12345"})
                self.assertEqual(code,200)
                self.assertIn("Secure",cookie)
                session=cookie.split(";",1)[0]
                code,status,_=call("GET","/api/status",cookie=session)
                self.assertEqual(code,200)
                self.assertEqual(status["control"]["mode"],"stopped")
                code,started,_=call("POST","/api/mode",{
                    "revision":status["control"]["revision"],"mode":"running"},
                    cookie=session,csrf=login["csrf"])
                self.assertEqual(code,200)
                self.assertEqual(started["control"]["mode"],"running")
                self.assertEqual(
                    json.loads((state/"control.json").read_text())["mode"],"running")
            finally:
                server.terminate()
                try:server.communicate(timeout=4)
                except subprocess.TimeoutExpired:server.kill()
                server.wait(timeout=4)


if __name__=="__main__":
    unittest.main(verbosity=2)
