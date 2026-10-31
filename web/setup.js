"use strict";
/* One browser-based installation wizard; also reused after sign-in for settings. */
const firstRun=location.pathname==="/setup.html" || location.pathname==="/";
const field=id=>document.getElementById("setup-"+id);
const form=document.getElementById("first-run-form");
let csrf="";
function providerUI(){
  const p=field("provider").value;
  document.getElementById("setup-ollama-group").classList.toggle("hidden",p!=="ollama");
  document.getElementById("setup-oauth-group").classList.toggle("hidden",!["chatgpt-oauth","gemini-oauth"].includes(p));
}
function values(){
  const str=id=>field(id).value.trim();
  return {
    ai_provider:str("provider"),ollama_url:str("ollama"),ai_model:str("model"),
    oauth_bridge_url:str("oauth-url"),oauth_model:str("oauth-model"),
    oauth_bridge_token:field("oauth-token").value,
    forecast_url:str("forecast"),forecast_mode:str("forecast-mode"),
    forecast_ai_review:field("forecast-ai-review").checked,
    schwab_app_key:str("schwab-key"),
    schwab_app_secret:field("schwab-secret").value,
    schwab_callback_url:str("schwab-callback"),
    paper_enabled:field("paper").checked,
    market_enabled:field("market").checked,
    paper_capital:Number(str("capital"))
  };
}
async function api(path,opts={}){
  const headers={"Content-Type":"application/json"};
  if(csrf && opts.method==="POST")headers["X-CSRF-Token"]=csrf;
  const response=await fetch(path,{credentials:"same-origin",cache:"no-store",...opts,headers});
  const doc=await response.json().catch(()=>({}));
  if(!response.ok)throw Error(doc.error||"Request failed");
  return doc;
}
let liveEnabled=false;
function setLiveButton(enabled){
  liveEnabled=enabled;
  const btn=document.getElementById("toggle-live");
  if(btn)btn.textContent=enabled?"Turn OFF live trading":"Turn ON live trading";
  const status=document.getElementById("live-current-status");
  if(status)status.textContent=enabled?
    "Live trading enabled. Real Schwab orders may be submitted.":
    "Live trading OFF. No new real orders are authorized.";
}
function displayError(error){
  field("error").textContent=error?.message||"Unable to complete setup";
}
async function init(){
  field("provider").addEventListener("change",providerUI);
  const callbackHelp=document.getElementById("automatic-callback-url");
  if(callbackHelp)callbackHelp.textContent=location.origin+"/schwab/callback";
  providerUI();
  const researchStatus=document.getElementById("forecast-test-status");
  const researchHint=document.getElementById("forecast-connection-hint");
  function updateResearchHint(){
    try{
      const ai=field("ollama").value.trim();
      const url=field("forecast").value.trim();
      if(url){researchHint.textContent="Using the manually entered forecast service URL.";return;}
      const host=new URL(ai).hostname;
      if(host && /^[0-9.]+$/.test(host))
        researchHint.textContent="Automatic discovery will check http://"+host+":8766 when no URL is entered.";
      else researchHint.textContent="Enter a forecast URL, or configure a private Ollama computer for automatic detection.";
    }catch(_){researchHint.textContent="Set an Ollama endpoint or enter the forecast service URL."; }
  }
  field("ollama").addEventListener("input",updateResearchHint);
  field("forecast").addEventListener("input",updateResearchHint);
  updateResearchHint();
  const researchTest=document.getElementById("test-forecast");
  const forecastMode=field("forecast-mode");
  if(forecastMode)forecastMode.addEventListener("change",()=>{
    researchHint.textContent=forecastMode.value==="built_in"?
      "Built-in research needs no external model service. Save this mode to use price/volume analysis directly.":
      "Optional external specialist service is normally on port 8766. Built-in analysis is the automatic fallback.";
  });
  researchTest.disabled=firstRun;
  if(researchTest)researchTest.addEventListener("click",async ()=>{
    researchTest.disabled=true;researchStatus.textContent="Checking research service…";
    try{
      if(forecastMode.value==="built_in"){
        researchStatus.textContent="Built-in forecast is available without a separate research workstation. Save settings and open Next session forecast to generate its first snapshot.";
        return;
      }
      let url=field("forecast").value.trim();
      if(!url && field("provider").value==="ollama"){
        const host=new URL(field("ollama").value.trim()).hostname;
        url="http://"+host+":8766";
      }
      const result=await api("/api/research/forecast/test",{
        method:"POST",body:JSON.stringify({forecast_url:url})});
      researchStatus.textContent="Connected — "+result.message+
        (result.last_refresh?" · Last refresh: "+result.last_refresh:"");
    }catch(e){researchStatus.textContent="Connection unavailable: "+e.message;}
    finally{researchTest.disabled=false;}
  });
  form.addEventListener("submit",async e=>{
    e.preventDefault();
    field("error").textContent="";
    const btn=field("submit");btn.disabled=true;
    try{
      const data=values();
      if(firstRun){
        const pass=field("password").value;
        if(pass!==field("confirm").value)throw Error("Administrator passwords do not match");
        if(pass.length<20)throw Error("Use an administrator password of at least 20 characters");
        data.setup_code=field("code").value.trim();
        data.admin_username=field("username").value.trim();
        data.admin_password=pass;
        await api("/api/setup/initialize",{method:"POST",body:JSON.stringify(data)});
        // Continue the same installation into Schwab OAuth without requiring
        // the user to hunt for Profile after creating the administrator.
        try {
          await api("/api/login",{method:"POST",body:JSON.stringify({
            username:data.admin_username,password:pass})});
          location.href="/integrations.html?onboarding=1#schwab-onboarding";
        } catch(_err) {
          // Credentials are already saved; if auto sign-in is interrupted,
          // use the normal sign-in form rather than attempting setup twice.
          location.href="/";
        }
      }else{
        await api("/api/integrations",{method:"POST",body:JSON.stringify(data)});
        field("oauth-token").value="";
        field("schwab-secret").value="";
        field("error").textContent="Settings saved. Private credentials are not shown again.";
      }
    }catch(ex){displayError(ex);}
    finally{btn.disabled=false;}
  });
  if(!firstRun){
    if(new URLSearchParams(location.search).get("onboarding")==="1"){
      const note=document.getElementById("onboarding-help");
      if(note){note.classList.remove("hidden");note.textContent="Your administrator account is ready. To finish installation, connect Schwab below (or skip for now), then return to Auto Trader. AI and forecast connections are independent.";}
    }
    try{
      csrf=(await api("/api/session")).csrf;
      const d=await api("/api/integrations");
      for(const [key,value] of Object.entries({
        provider:d.ai_provider,ollama:d.ollama_url,model:d.ai_model,
        "oauth-url":d.oauth_bridge_url,"oauth-model":d.oauth_model,
        forecast:d.forecast_url,"forecast-mode":d.forecast_mode,
        "schwab-key":d.schwab_app_key,
        "schwab-callback":d.schwab_callback_url,
        capital:d.paper_capital
      })){if(field(key)&&value!==undefined)field(key).value=value;}
      field("forecast-ai-review").checked=!!d.forecast_ai_review;
      field("paper").checked=!!d.paper_enabled;
      field("market").checked=!!d.market_enabled;
      providerUI();
      document.getElementById("schwab-status").textContent=
        d.schwab_token_connected?"Schwab OAuth connected":"Schwab account not connected";
      setLiveButton(!!d.live_enabled);
      const steps=d.setup_status||{};
      document.getElementById("setup-checklist").textContent=
        "Account: "+(steps.administrator||"pending")+" · AI: "+(steps.ai||"optional")+
        " · Schwab: "+(steps.schwab_account||"not_connected")+
        " · Paper: "+(steps.paper||"off")+
        " · Market quotes: "+(steps.market_quotes||"off");
    }catch(e){displayError(e);}
    document.getElementById("toggle-live").addEventListener("click",async ()=>{
      try{
        const enabling=!liveEnabled;
        if(enabling){
          const account=field("live-account").value;
          if(!account)throw Error("Connect Schwab and select the verified brokerage account first.");
          if(!window.confirm("ENABLE LIVE TRADING? This allows Auto Trader to submit REAL Schwab buy and sell orders in your selected account. You can lose money. Continue?"))return;
          const data=await api("/api/live/activation",{method:"POST",
            body:JSON.stringify({enable:true,confirmed:true,account_hash:account})});
          setLiveButton(data.live_enabled===true);
        }else{
          const data=await api("/api/live/activation",{method:"POST",
            body:JSON.stringify({enable:false,confirmed:true,account_hash:""})});
          setLiveButton(!!data.live_enabled);
        }
      }catch(ex){displayError(ex);}
    });
    document.getElementById("fetch-accounts").addEventListener("click",async ()=>{
      try{
        const data=await api("/api/schwab/accounts");
        const select=field("live-account");select.replaceChildren();
        for(const row of data.accounts||[]){
          const op=document.createElement("option");op.value=row.hash;
          op.textContent=row.label;select.appendChild(op);
        }
        if(!select.options.length)throw Error("No authorized Schwab accounts found");
      }catch(ex){displayError(ex);}
    });
    document.getElementById("connect-schwab").addEventListener("click",async ()=>{
      try{
        const result=await api("/api/schwab/authorize",{method:"POST",body:"{}"});
        const anchor=document.getElementById("schwab-oauth-link");
        anchor.textContent="Open Schwab sign-in";anchor.href=result.authorization_url;
        anchor.classList.remove("hidden");
        const helper=document.getElementById("schwab-callback-help");
        if(helper)helper.textContent=result.instructions||"";
        document.getElementById("schwab-redirect-form").classList.toggle("hidden",result.automatic_callback===true);
      }catch(e){displayError(e);}
    });
    document.getElementById("finish-schwab").addEventListener("click",async e=>{
      e.preventDefault();
      try{
        await api("/api/schwab/complete",{method:"POST",
          body:JSON.stringify({redirected_url:document.getElementById("schwab-redirect-url").value.trim()})});
        document.getElementById("schwab-status").textContent="Schwab OAuth connected";
        document.getElementById("schwab-redirect-form").classList.add("hidden");
        field("error").textContent="Schwab connected. Live trading remains off.";
      }catch(ex){displayError(ex);}
    });
  }
}
document.addEventListener("DOMContentLoaded",init);
