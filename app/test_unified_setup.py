"""Public installation: first-run pairing, persistent password and AI/Schwab GUI configuration."""
import http.client,json,os,socket,ssl,subprocess,sys,tempfile,time,unittest
from pathlib import Path
APP=Path(__file__).resolve().parent
PASSWORD="a-test-admin-password-that-is-long-enough-2026"
FALLBACK="never-shared-generated-startup-password-123456789"

class UnifiedWizardTests(unittest.TestCase):
 def test_first_run_setup_and_integrations_survive_restart(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);state=root/"state";state.mkdir()
   cert=root/"cert.pem";key=root/"key.pem"
   p=subprocess.run(["openssl","req","-x509","-newkey","ec",
     "-pkeyopt","ec_paramgen_curve:prime256v1","-nodes",
     "-keyout",str(key),"-out",str(cert),"-days","1","-subj","/CN=localhost"],
      capture_output=True,text=True,timeout=18)
   self.assertEqual(p.returncode,0,p.stderr)
   with socket.socket() as sock:
    sock.bind(("127.0.0.1",0));port=sock.getsockname()[1]
   env=dict(os.environ,AUTO_UNIFIED_APP="true",STATE_DIR=str(state),
      DASHBOARD_PASSWORD=FALLBACK,DASHBOARD_SESSION_SECRET="synthetic-session-secret-123456789123456789",
      DASHBOARD_TLS_CERT=str(cert),DASHBOARD_TLS_KEY=str(key),
      DASHBOARD_STATIC_DIR=str(APP.parent/"web"),
      DASHBOARD_BIND="127.0.0.1",DASHBOARD_PORT=str(port))
   context=ssl._create_unverified_context()
   def request(method,path,body=None,cookie=None,csrf=None):
    conn=http.client.HTTPSConnection("127.0.0.1",port,context=context,timeout=6)
    headers={"Origin":f"https://127.0.0.1:{port}"}
    if body is not None:headers["Content-Type"]="application/json"
    if csrf:headers["X-CSRF-Token"]=csrf
    if cookie:headers["Cookie"]=cookie
    conn.request(method,path,None if body is None else json.dumps(body),headers)
    res=conn.getresponse();raw=res.read()
    typ=res.getheader("Content-Type","")
    doc=json.loads(raw) if typ.startswith("application/json") else raw.decode()
    retval=(res.status,doc,res.getheader("Set-Cookie",""))
    conn.close();return retval
   def launch():
    proc=subprocess.Popen([sys.executable,"-u","dashboard_server.py"],
      cwd=APP,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    for _ in range(65):
     if proc.poll() is not None:raise RuntimeError(proc.stderr.read().decode()[-900:])
     try:
      if request("GET","/health")[0]==200:return proc
     except(OSError,ssl.SSLError):time.sleep(.1)
    raise RuntimeError("HTTPS server did not start")
   def stop(proc):
    proc.terminate()
    try:proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:proc.kill();proc.wait()
   proc=launch()
   try:
    status,page,_=request("GET","/")
    self.assertEqual(status,200)
    self.assertIn("Set up your trading workstation",page)
    self.assertEqual(request("GET","/api/setup/status")[1]["setup_needed"],True)
    self.assertEqual(request("POST","/api/login",{"username":"admin","password":PASSWORD})[0],409)
    from unified_config import pairing_code
    code=pairing_code(state)
    data={"setup_code":code,"admin_username":"admin","admin_password":PASSWORD,
      "ai_provider":"ollama","ollama_url":"http://192.168.1.21:11434",
      "ai_model":"qwen3.5:4b","paper_enabled":False,"market_enabled":False}
    bad=dict(data,setup_code="bad")
    self.assertEqual(request("POST","/api/setup/initialize",bad)[0],400)
    status,out,_=request("POST","/api/setup/initialize",data)
    self.assertEqual(status,200,out)
    self.assertFalse((state/".setup_code").exists())
    self.assertEqual(request("POST","/api/setup/initialize",data)[0],400)
    self.assertEqual(request("GET","/api/setup/status")[1]["setup_needed"],False)
    self.assertEqual(request("GET","/api/integrations")[0],401)
    status,session,raw_cookie=request("POST","/api/login",{"username":"admin","password":PASSWORD})
    self.assertEqual(status,200,session)
    cookie=raw_cookie.split(";",1)[0];token=session["csrf"]
    status,public,_=request("GET","/api/integrations",cookie=cookie)
    self.assertEqual(status,200)
    self.assertEqual(public["ollama_url"],"http://192.168.1.21:11434")
    self.assertNotIn("schwab_app_secret",public)
    status,_,_=request("POST","/api/integrations",{
      "ai_provider":"none","schwab_app_key":"fake-user-dev-key",
      "schwab_app_secret":"synthetic-test-secret-not-real",
      "schwab_callback_url":"https://127.0.0.1:8182",
      "paper_enabled":False,"market_enabled":False},cookie=cookie,csrf=token)
    self.assertEqual(status,200)
    self.assertNotIn("synthetic-test-secret-not-real",(state/"config"/"integrations.json").read_text())
    self.assertEqual((state/"config"/"credentials.json").stat().st_mode & 0o777,0o600)
    status,after,_=request("GET","/api/integrations",cookie=cookie)
    self.assertEqual(status,200)
    self.assertTrue(after["schwab_secret_set"])
    self.assertNotIn("schwab_app_secret",after)
    status,_,_=request("POST","/api/integrations",{
      "ai_provider":"ollama","ollama_url":"http://8.8.8.8:11434"
      },cookie=cookie,csrf=token)
    self.assertEqual(status,400)
   finally:stop(proc)
   proc=launch()
   try:
    self.assertEqual(request("POST","/api/login",{"username":"admin","password":PASSWORD})[0],200)
    self.assertEqual(request("GET","/api/setup/status")[1]["setup_needed"],False)
   finally:stop(proc)

if __name__=="__main__":unittest.main()
