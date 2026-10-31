"use strict";
/* First run: admin + AI only. AI settings and Schwab are independently managed. */
const firstRun=location.pathname==="/setup.html" || location.pathname==="/";
const field=id=>document.getElementById("setup-"+id);
const byId=id=>document.getElementById(id);
const form=byId("first-run-form");
let csrf="";
let liveEnabled=false;

function providerUI(){
  if(!field("provider"))return;
  const p=field("provider").value;
  const ollama=byId("setup-ollama-group");
  const oauth=byId("setup-oauth-group");
  if(ollama)ollama.classList.toggle("hidden",p!=="ollama");
  if(oauth)oauth.classList.toggle("hidden",!["chatgpt-oauth","gemini-oauth"].includes(p));
}
function values(){
  // Partial updates: AI settings never overwrite broker credentials, and
  // broker settings never clear selected AI models or simulator state.
  const fields={
    ai_provider:"provider",ollama_url:"ollama",ai_model:"model",
    oauth_bridge_url:"oauth-url",oauth_model:"oauth-model",
    oauth_bridge_token:"oauth-token",forecast_url:"forecast",
    forecast_mode:"forecast-mode",schwab_app_key:"schwab-key",
    schwab_app_secret:"schwab-secret",schwab_callback_url:"schwab-callback",
  };
  const result={};
  for(const [key,id] of Object.entries(fields)){
    const input=field(id);
    if(input)result[key]=input.value.trim();
  }
  const switches={
    forecast_ai_review:"forecast-ai-review",paper_enabled:"paper",
    market_enabled:"market"
  };
  for(const [key,id] of Object.entries(switches)){
    const input=field(id);
    if(input)result[key]=input.checked;
  }
  if(field("capital"))result.paper_capital=Number(field("capital").value);
  return result;
}
async function api(path,opts={}){
  const headers={"Content-Type":"application/json"};
  if(csrf && opts.method==="POST")headers["X-CSRF-Token"]=csrf;
  const response=await fetch(path,{credentials:"same-origin",cache:"no-store",...opts,headers});
  const doc=await response.json().catch(()=>({}));
  if(!response.ok)throw Error(doc.error||"Request failed");
  return doc;
}
function displayError(error){
  const label=field("error");
  if(label)label.textContent=error?.message||"Unable to complete setup";
}
function setLiveButton(enabled){
  liveEnabled=enabled;
  const button=byId("toggle-live");
  if(button)button.textContent=enabled?"Turn OFF live trading":"Turn ON live trading";
  const label=byId("live-current-status");
  if(label)label.textContent=enabled?
    "Live trading enabled. Real Schwab orders may be submitted.":
    "Live trading OFF. No new real orders are authorized.";
}
function validNewPassword(value){
  return typeof value==="string" && value.length>=10 && value.length<=256 &&
    /[A-Z]/.test(value) && /[0-9]/.test(value) &&
    /[^\p{L}\p{N}\s]/u.test(value) && !/[\x00-\x1F\x7F]/.test(value);
}
function setupForecast(){
  const hint=byId("forecast-connection-hint");
  const test=byId("test-forecast");
  const status=byId("forecast-test-status");
  const mode=field("forecast-mode");
  if(!hint||!test||!status||!mode)return;
  function refreshHint(){
    if(mode.value==="built_in"){
      hint.textContent="No separate service required: NAS built-in market analysis is available.";
      return;
    }
    const explicit=field("forecast")?.value.trim()||"";
    if(explicit){
      hint.textContent="Using the optional, manually configured specialist forecast service.";
      return;
    }
    const ai=field("ollama")?.value.trim()||"";
    try{
      const host=new URL(ai).hostname;
      hint.textContent=/^[0-9.]+$/.test(host)?
        "Automatic discovery will check http://"+host+":8766. Built-in remains the fallback.":
        "Advanced forecasting is optional; automatic mode uses NAS built-in research if none is connected.";
    }catch(_){
      hint.textContent="Advanced forecasting is optional; NAS built-in research remains available.";
    }
  }
  for(const id of ["forecast-mode","forecast","ollama"]){
    const input=field(id);
    if(input)input.addEventListener("input",refreshHint);
  }
  refreshHint();
  test.disabled=firstRun;
  test.addEventListener("click",async()=>{
    test.disabled=true;
    status.textContent="Checking research connection…";
    try{
      if(mode.value==="built_in"){
        status.textContent="Built-in NAS research is available. No additional forecast model is required.";
        return;
      }
      let url=field("forecast")?.value.trim()||"";
      if(!url && field("provider")?.value==="ollama"){
        const host=new URL(field("ollama").value.trim()).hostname;
        url="http://"+host+":8766";
      }
      const result=await api("/api/research/forecast/test",{
        method:"POST",body:JSON.stringify({forecast_url:url})});
      status.textContent="Connected — "+result.message+
        (result.last_refresh?" · Last refresh: "+result.last_refresh:"");
    }catch(error){
      status.textContent="Connection unavailable: "+error.message;
    }finally{test.disabled=false;}
  });
}
async function saveSettings(e){
  e.preventDefault();
  const label=field("error");
  if(label)label.textContent="";
  const button=field("submit");
  if(button)button.disabled=true;
  try{
    const data=values();
    if(firstRun){
      const password=field("password").value;
      if(password!==field("confirm").value)throw Error("Administrator passwords do not match");
      if(!validNewPassword(password))
        throw Error("Use at least 10 characters with an uppercase letter, a number and a symbol.");
      data.setup_code=field("code").value.trim();
      data.admin_username=field("username").value.trim();
      data.admin_password=password;
      await api("/api/setup/initialize",{method:"POST",body:JSON.stringify(data)});
      try{
        const session=await api("/api/login",{method:"POST",body:JSON.stringify({
          username:data.admin_username,password})});
        csrf=session.csrf;
        location.href="/";
      }catch(_){
        location.href="/";
      }
    }else{
      await api("/api/integrations",{method:"POST",body:JSON.stringify(data)});
      for(const id of ["oauth-token","schwab-secret"]){
        if(field(id))field(id).value="";
      }
      if(label)label.textContent="Settings saved. Sensitive values are not shown again.";
    }
  }catch(error){displayError(error);}
  finally{if(button)button.disabled=false;}
}
async function loadSaved(){
  csrf=(await api("/api/session")).csrf;
  const d=await api("/api/integrations");
  const keys={
    provider:"ai_provider",ollama:"ollama_url",model:"ai_model",
    "oauth-url":"oauth_bridge_url","oauth-model":"oauth_model",
    forecast:"forecast_url","forecast-mode":"forecast_mode",
    "schwab-key":"schwab_app_key","schwab-callback":"schwab_callback_url",
    capital:"paper_capital"
  };
  for(const [id,key] of Object.entries(keys)){
    if(field(id) && d[key]!==undefined)field(id).value=d[key];
  }
  for(const [id,key] of Object.entries({
    "forecast-ai-review":"forecast_ai_review",paper:"paper_enabled",
    market:"market_enabled"
  })){
    if(field(id))field(id).checked=!!d[key];
  }
  providerUI();
  const schwabStatus=byId("schwab-status");
  if(schwabStatus)schwabStatus.textContent=d.schwab_token_connected?
    "Schwab authorization saved — verify broker account status before live trading":
    "Schwab account not connected";
  setLiveButton(!!d.live_enabled);
  const checklist=byId("setup-checklist");
  if(checklist){
    const steps=d.setup_status||{};
    checklist.textContent="Schwab: "+(steps.schwab_account||"not_connected")+
      " · Market quotes: "+(steps.market_quotes||"off")+
      " · Live orders: "+(steps.live||"off");
  }
}
function bindBrokerControls(){
  const toggle=byId("toggle-live");
  if(toggle)toggle.addEventListener("click",async()=>{
    try{
      const enabling=!liveEnabled;
      if(enabling){
        const account=field("live-account")?.value||"";
        if(!account)throw Error("Connect Schwab and choose an authorized account first.");
        if(!window.confirm("ENABLE LIVE TRADING? This permits REAL Schwab buy and sell orders in this account. You can lose money. Continue?"))return;
        const doc=await api("/api/live/activation",{method:"POST",body:JSON.stringify({
          enable:true,confirmed:true,account_hash:account})});
        setLiveButton(doc.live_enabled===true);
      }else{
        const doc=await api("/api/live/activation",{method:"POST",body:JSON.stringify({
          enable:false,confirmed:true,account_hash:""})});
        setLiveButton(!!doc.live_enabled);
      }
    }catch(error){displayError(error);}
  });
  const fetchAccounts=byId("fetch-accounts");
  if(fetchAccounts)fetchAccounts.addEventListener("click",async()=>{
    try{
      const response=await api("/api/schwab/accounts");
      const select=field("live-account");
      select.replaceChildren();
      for(const row of response.accounts||[]){
        const option=document.createElement("option");
        option.value=row.hash;option.textContent=row.label;select.appendChild(option);
      }
      if(!select.options.length)throw Error("No authorized Schwab accounts found.");
    }catch(error){displayError(error);}
  });
  const connect=byId("connect-schwab");
  if(connect)connect.addEventListener("click",async()=>{
    try{
      const response=await api("/api/schwab/authorize",{method:"POST",body:"{}"});
      const anchor=byId("schwab-oauth-link");
      anchor.textContent="Open official Schwab sign-in";
      anchor.href=response.authorization_url;
      anchor.classList.remove("hidden");
      const help=byId("schwab-callback-help");
      if(help)help.textContent=response.instructions||"";
      byId("schwab-redirect-form").classList.toggle("hidden",response.automatic_callback===true);
    }catch(error){displayError(error);}
  });
  const finish=byId("finish-schwab");
  if(finish)finish.addEventListener("click",async event=>{
    event.preventDefault();
    try{
      await api("/api/schwab/complete",{method:"POST",body:JSON.stringify({
        redirected_url:byId("schwab-redirect-url").value.trim()})});
      byId("schwab-status").textContent="Schwab authorization saved";
      byId("schwab-redirect-form").classList.add("hidden");
      byId("schwab-redirect-url").value="";
      const label=field("error");
      if(label)label.textContent="Schwab connected. Live orders remain separately controlled.";
    }catch(error){displayError(error);}
  });
}
async function init(){
  if(field("provider"))field("provider").addEventListener("change",providerUI);
  const callback=byId("automatic-callback-url");
  if(callback)callback.textContent=location.origin+"/schwab/callback";
  providerUI();
  setupForecast();
  if(form)form.addEventListener("submit",saveSettings);
  if(!firstRun){
    try{await loadSaved();}
    catch(error){displayError(error);}
    bindBrokerControls();
  }
}
document.addEventListener("DOMContentLoaded",init);
