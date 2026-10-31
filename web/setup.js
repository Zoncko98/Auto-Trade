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
    forecast_url:str("forecast"),schwab_app_key:str("schwab-key"),
    schwab_app_secret:field("schwab-secret").value,
    schwab_callback_url:str("schwab-callback"),
    paper_enabled:field("paper").checked,
    market_enabled:field("market").checked,
    paper_capital:Number(str("capital")),
    ...(firstRun ? {} : {
       live_enabled:field("live-enabled").checked,
       live_account_hash:field("live-account").value,
       live_activation_phrase:field("live-phrase").value.trim()
    })
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
function displayError(error){
  field("error").textContent=error?.message||"Unable to complete setup";
}
async function init(){
  field("provider").addEventListener("change",providerUI);
  providerUI();
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
        location.href="/";
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
    try{
      csrf=(await api("/api/session")).csrf;
      const d=await api("/api/integrations");
      for(const [key,value] of Object.entries({
        provider:d.ai_provider,ollama:d.ollama_url,model:d.ai_model,
        "oauth-url":d.oauth_bridge_url,"oauth-model":d.oauth_model,
        forecast:d.forecast_url,"schwab-key":d.schwab_app_key,
        "schwab-callback":d.schwab_callback_url,
        capital:d.paper_capital
      })){if(field(key)&&value!==undefined)field(key).value=value;}
      field("paper").checked=!!d.paper_enabled;
      field("market").checked=!!d.market_enabled;
      providerUI();
      document.getElementById("schwab-status").textContent=
        d.schwab_token_connected?"Schwab OAuth connected":"Schwab account not connected";
      field("live-enabled").checked=!!d.live_enabled;
    }catch(e){displayError(e);}
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
        document.getElementById("schwab-redirect-form").classList.remove("hidden");
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
