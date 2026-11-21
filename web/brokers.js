"use strict";
/* Read-only broker discovery view. It does not manage or authorize orders. */
const BROKER_DOC_DOMAINS=new Set([
 "developer.schwab.com","developer.webull.com","docs.alpaca.markets",
 "docs.robinhood.com","www.interactivebrokers.com"
]);
function brokerEl(tag,text,cls){
  const node=document.createElement(tag);
  if(text!=null)node.textContent=String(text);
  if(cls)node.className=cls;
  return node;
}
function brokerLink(url,label){
  const a=brokerEl("a",label);
  try{
    const path=new URL(url);
    if(path.protocol==="https:" && BROKER_DOC_DOMAINS.has(path.hostname)){
      a.href=path.href;
      a.target="_blank";
      a.rel="noopener noreferrer";
    }
  }catch(_){}
  return a;
}
function brokerRow(parent,title,detail){
  const row=brokerEl("div",null,"broker-capabilities");
  const label=brokerEl("strong",title);
  row.append(label,brokerEl("span",detail));
  parent.appendChild(row);
}

function schwabInlineCard(card){
  card.id="broker-schwab-inline";
  const section=brokerEl("section",null,"broker-capabilities schwab-inline");
  const title=brokerEl("h3","Schwab connection");
  const status=brokerEl("p","Checking saved Schwab authorization…","broker-note");
  status.id="schwab-inline-status";
  status.setAttribute("role","status");
  const hint=brokerEl("p",
    "One connection action handles first-time setup and expired authorizations. Schwab sign-in is always completed on Schwab's website; authorization never starts trading.",
    "broker-note");
  const begin=brokerEl("button","Connect / Reconnect Schwab","btn primary");
  begin.type="button";begin.id="schwab-inline-connect";begin.disabled=true;
  const link=brokerEl("a","Open official Schwab sign-in","btn secondary hidden");
  link.id="schwab-inline-oauth-link";link.target="_blank";link.rel="noopener noreferrer";
  const step=brokerEl("p","","broker-note");
  step.id="schwab-inline-step";
  const redirect=brokerEl("form",null,"broker-actions hidden");
  redirect.id="schwab-inline-callback-form";redirect.autocomplete="off";
  const label=brokerEl("label","Paste complete Schwab redirect URL");
  label.htmlFor="schwab-inline-redirect";
  const input=brokerEl("input");
  input.id="schwab-inline-redirect";input.type="url";
  input.autocomplete="off";input.placeholder="https://127.0.0.1:8182/?code=…";
  input.required=true;
  const finish=brokerEl("button","Finish Schwab connection","btn secondary");
  finish.type="submit";
  redirect.append(label,input,finish);
  const controls=brokerEl("div",null,"broker-actions");
  controls.append(begin,link);
  const restart=brokerEl("button","Start a new sign-in","btn secondary hidden");
  restart.type="button";restart.id="schwab-inline-restart";
  controls.append(restart);
  const refresh=brokerEl("button","Refresh Schwab status","btn secondary");
  refresh.type="button";refresh.id="schwab-inline-refresh";
  controls.append(refresh);

  const accounts=brokerEl("details",null,"broker-capabilities");
  const accountLabel=brokerEl("summary","Verify account & enable live permissions");
  const accountInfo=brokerEl("p",
    "Account verification is read-only. Live trading permission requires selecting an authorized account and an explicit real-money confirmation. Risk and order safeguards remain active.","broker-note");
  const list=brokerEl("select");
  list.id="schwab-inline-account";list.setAttribute("aria-label","Verified Schwab account");
  const lookup=brokerEl("button","Verify Schwab accounts","btn secondary");lookup.type="button";
  const activate=brokerEl("button","Enable live Schwab orders","btn danger-outline");activate.type="button";activate.disabled=true;
  const accountState=brokerEl("p","Schwab account not verified in this session.","broker-note");
  accountState.setAttribute("role","status");
  const accountButtons=brokerEl("div",null,"broker-actions");
  accountButtons.append(lookup,activate);
  accounts.append(accountLabel,accountInfo,list,accountButtons,accountState);

  const settings=brokerEl("details",null,"broker-capabilities");
  settings.id="schwab-inline-settings";
  settings.append(brokerEl("summary","Developer credentials & registered callback (advanced)"));
  const form=brokerEl("form",null,"broker-actions");
  form.autocomplete="off";
  const keyLabel=brokerEl("label","Schwab developer app key");
  const key=brokerEl("input");key.id="schwab-inline-key";key.type="text";
  key.autocomplete="off";key.maxLength=256;
  const secretLabel=brokerEl("label","Schwab developer app secret");
  const secret=brokerEl("input");secret.id="schwab-inline-secret";secret.type="password";
  secret.autocomplete="new-password";secret.maxLength=256;
  const cbLabel=brokerEl("label","Exact registered HTTPS callback URL");
  const callback=brokerEl("input");callback.id="schwab-inline-callback";callback.type="url";
  callback.required=true;callback.value="https://127.0.0.1:8182";
  const cbHelp=brokerEl("p",
    "Keep the callback registered in your Schwab developer application. The default loopback URL uses the paste-to-finish step. An automatic NAS callback works only when registered at Schwab with the exact private-NAS HTTPS address.","broker-note");
  const save=brokerEl("button","Save Schwab developer settings","btn secondary");save.type="submit";
  const saveState=brokerEl("p","","broker-note");saveState.setAttribute("role","status");
  form.append(keyLabel,key,secretLabel,secret,cbLabel,callback,cbHelp,save,saveState);
  settings.append(form);
  section.append(title,status,hint,controls,step,redirect,accounts,settings);
  card.append(section);

  let credentialReady=false;
  async function reload(){
    const [config,live]=await Promise.all([
      request("/api/integrations"),request("/api/live")]);
    credentialReady=Boolean(config.schwab_app_key&&config.schwab_secret_set);
    key.value=String(config.schwab_app_key||"");
    callback.value=String(config.schwab_callback_url||"https://127.0.0.1:8182");
    secret.value="";
    secret.placeholder=config.schwab_secret_set?
      "Saved securely — leave blank to keep":"Enter developer app secret";
    begin.disabled=!credentialReady;
    if(!credentialReady){
      status.textContent="Save developer key and secret below to connect Schwab.";
      settings.open=true;
    }else if(live.auth_state==="REAUTH_REQUIRED"||
             live.worker_supervisor?.state==="REAUTH_REQUIRED"){
      status.textContent="Schwab authorization expired or was revoked. Select Connect / Reconnect Schwab for a fresh official sign-in. Existing tokens will not block replacement.";
    }else if(live.auth_state==="WORKER_VERIFIED"&&live.worker_online){
      status.textContent="Schwab worker verified and online. Order permission: "+
        String(live.order_permission||"unverified")+".";
    }else if(config.schwab_token_connected){
      status.textContent="Authorization file saved; broker verification is still required. Worker: "+
        String(live.worker_supervisor?.state||"unverified")+".";
    }else{
      status.textContent="Developer credentials saved. Connect Schwab to authorize an account.";
    }
    if(config.live_enabled===true){
      accountState.textContent="Schwab live-account permission saved. Actual order submission still requires an online authenticated worker, reconciliation and risk checks.";
    }
  }
  async function startOAuth(restartSession=false){
    begin.disabled=true;restart.disabled=true;
    status.textContent="Preparing official Schwab authorization…";
    try{
      const response=await request("/api/schwab/connect",{
        method:"POST",body:JSON.stringify(restartSession?{restart:true}:{})});
      const url=new URL(response.authorization_url);
      if(url.protocol!=="https:"||url.hostname!=="api.schwabapi.com")
        throw Error("Schwab returned an unrecognized authorization address");
      link.href=url.href;link.classList.remove("hidden");
      restart.classList.remove("hidden");
      redirect.classList.toggle("hidden",response.automatic_callback===true);
      step.textContent=String(response.instructions||"");
      status.textContent=response.resumed?
        "Existing sign-in session resumed. Open the official sign-in link to finish.":
        "Authorization ready. Open official Schwab sign-in.";
    }catch(error){
      status.textContent="Schwab connection not started: "+String(error.message||error);
    }finally{begin.disabled=!credentialReady;restart.disabled=false;}
  }
  begin.addEventListener("click",()=>startOAuth());
  restart.addEventListener("click",()=>startOAuth(true));
  redirect.addEventListener("submit",async event=>{
    event.preventDefault();finish.disabled=true;
    try{
      await request("/api/schwab/complete",{
        method:"POST",body:JSON.stringify({redirected_url:input.value.trim()})});
      input.value="";redirect.classList.add("hidden");link.classList.add("hidden");
      restart.classList.add("hidden");link.removeAttribute("href");
      step.textContent="Authorization replaced safely. Verify the account before enabling live trading.";
      await reload();
    }catch(error){
      status.textContent="Unable to finish Schwab authorization: "+String(error.message||error);
    }finally{finish.disabled=false;}
  });
  refresh.addEventListener("click",()=>reload().catch(error=>{
    status.textContent="Schwab status unavailable: "+String(error.message||error);
  }));
  form.addEventListener("submit",async event=>{
    event.preventDefault();save.disabled=true;
    try{
      const config={
        schwab_app_key:key.value.trim(),
        schwab_callback_url:callback.value.trim()
      };
      if(secret.value.trim())config.schwab_app_secret=secret.value.trim();
      await request("/api/integrations",{method:"POST",body:JSON.stringify(config)});
      secret.value="";saveState.textContent="Developer settings saved securely.";
      await reload();
      settings.open=false;
    }catch(error){
      secret.value="";
      saveState.textContent="Unable to save Schwab settings: "+String(error.message||error);
    }finally{save.disabled=false;}
  });
  lookup.addEventListener("click",async()=>{
    lookup.disabled=true;
    list.replaceChildren();activate.disabled=true;
    accountState.textContent="Verifying authorized accounts with Schwab…";
    try{
      const doc=await request("/api/schwab/accounts");
      const rows=Array.isArray(doc.accounts)?doc.accounts:[];
      for(const row of rows){
        if(!row || typeof row.hash!=="string")continue;
        const option=brokerEl("option",String(row.label||"Verified account"));
        option.value=row.hash;list.append(option);
      }
      if(!list.options.length)throw Error("No verified Schwab account returned");
      accountState.textContent=list.options.length+" Schwab account(s) verified. Select an account before enabling orders.";
      activate.disabled=false;
    }catch(error){
      accountState.textContent="Account verification unavailable: "+String(error.message||error);
    }finally{lookup.disabled=false;}
  });
  activate.addEventListener("click",async()=>{
    if(!list.value)return;
    if(!window.confirm("ENABLE REAL-MONEY SCHWAB TRADING for the selected verified account? Buy and sell orders may execute under saved risk limits. Continue?"))return;
    activate.disabled=true;
    try{
      const outcome=await request("/api/live/activation",{method:"POST",
        body:JSON.stringify({enable:true,confirmed:true,account_hash:list.value})});
      if(outcome.live_enabled!==true)throw Error("Broker authorization did not enable trading");
      accountState.textContent="Live permission saved. Schwab worker and risk checks must still pass before any order.";
      await reload();
    }catch(error){
      accountState.textContent="Schwab trading was not enabled: "+String(error.message||error);
    }finally{activate.disabled=false;}
  });
  reload().catch(error=>{
    begin.disabled=true;
    status.textContent="Schwab connection status unavailable: "+String(error.message||error);
  });
}

function brokerCard(broker){
  const card=brokerEl("article",null,"broker-card");
  const heading=brokerEl("div",null,"broker-card-heading");
  const title=brokerEl("h2",broker.name);
  const live=broker.integration_status==="authorization_saved";
  const label=brokerEl("span",
    broker.id==="schwab"?"Check OAuth below":
    live?"Authorization file saved":
    broker.integration_status==="approval_required"?"Developer approval":
    broker.integration_status==="configuration_saved"?"Credentials loaded":
    broker.integration_status==="credentials_required"?"Setup required":
    broker.integration_status==="crypto_only"?"Crypto API only":
    broker.integration_status==="not_connected"?"Not connected":"Not yet integrated",
    "broker-status"+(live?" connected":""));
  heading.append(title,label);
  card.appendChild(heading);
  card.appendChild(brokerEl("p",broker.description));
  brokerRow(card,"Official authentication",broker.auth_method);
  brokerRow(card,"Supported product types",Array.isArray(broker.assets)?broker.assets.join(", "):"Not verified");
  brokerRow(card,"Auto Trader connected?",broker.id==="schwab"?
    "Verify current OAuth and account below":
    broker.app_account_connected?
    "Saved authorization (revalidate with broker before orders)":"No");
  brokerRow(card,"Auto Trader live orders",broker.app_orders_supported?
    "Existing Schwab worker only; live permission is a separate step":
    "Not implemented / disabled");
  card.appendChild(brokerEl("p",broker.setup_requirement,"broker-note"));
  if(broker.id==="webull"){
    const health=brokerEl("p","Webull connection: checking…","broker-note");
    const accounts=brokerEl("div",null,"broker-capabilities");
    const setup=brokerEl("form",null,"broker-actions");
    setup.autocomplete="off";
    const kl=brokerEl("label","Webull App Key");
    const key=document.createElement("input");key.type="text";key.required=true;key.autocomplete="off";
    const sl=brokerEl("label","Webull App Secret");
    const secret=document.createElement("input");secret.type="password";secret.required=true;secret.autocomplete="new-password";
    const el=brokerEl("label","API environment");
    const env=document.createElement("select");
    [["sandbox","Sandbox (testing)"],["production","Production (read-only until verified)"]].forEach(([v,t])=>{
      const opt=brokerEl("option",t);opt.value=v;env.appendChild(opt);
    });
    const submit=brokerEl("button","Save Webull API credentials");submit.type="submit";
    setup.append(kl,key,sl,secret,el,env,submit);
    async function refresh(){
      const data=await request("/api/webull/status");
      if(typeof updateWebullTile==="function")updateWebullTile(data);
      accounts.replaceChildren();
      health.textContent=data.connected?
        "Webull authenticated · "+data.environment+" · live order authority configured under Risk & trading controls":
        "Webull not connected · "+(data.reason||"Credentials required");
      if(data.connected){
        (data.accounts||[]).filter(a=>
           !/CASH/i.test(a.account_type||"")||/CRYPTO/i.test(a.account_type||"")
        ).forEach(a=>brokerRow(accounts,"Account "+a.account_id,a.account_type||"Type unavailable"));
        const excluded=(data.accounts||[]).filter(a=>
           /CASH/i.test(a.account_type||"")&&!/CRYPTO/i.test(a.account_type||"")).length;
        if(excluded)brokerRow(accounts,"Trading account visibility",
           excluded+" cash-classified account(s) hidden · not removed from Webull");
      }
    }
    setup.addEventListener("submit",async e=>{
      e.preventDefault();submit.disabled=true;
      try{
        await request("/api/webull/connect",{method:"POST",body:JSON.stringify({
          app_key:key.value.trim(),app_secret:secret.value.trim(),environment:env.value})});
        await refresh();
      }catch(error){health.textContent="Webull setup error: "+error.message;}
      finally{key.value="";secret.value="";submit.disabled=false;}
    });
    card.append(health,accounts,setup);
    const streamHeader=brokerEl("h3","Webull market data");
    const streamNote=brokerEl("p","US stock discovery uses Webull's own OpenAPI quotes and one-minute bars. "+
      "Crypto discovery uses the public Coinbase ticker WebSocket; Coinbase prices are indicative only. "+
      "All executable quotes and spread checks come from Webull. No additional market-data API keys are needed.",
      "broker-note");
    card.append(streamHeader,streamNote);
    refresh().catch(()=>{health.textContent="Webull status unavailable";});
  }
  if(broker.id==="robinhood_crypto"){
    const health=brokerEl("p","Robinhood connection: checking…","broker-note");
    const accountDetails=brokerEl("div",null,"broker-capabilities");
    const setup=brokerEl("form",null,"broker-actions");
    setup.autocomplete="off";
    const keyLabel=brokerEl("label","Robinhood API key identifier");
    const keyInput=document.createElement("input");
    keyInput.type="text";keyInput.name="robinhood-key";keyInput.required=true;
    keyInput.autocomplete="off";keyInput.placeholder="rh-api-...";
    const signingLabel=brokerEl("label","Ed25519 private signing key (Base64)");
    const signingInput=document.createElement("input");
    signingInput.type="password";signingInput.name="robinhood-signing-key";
    signingInput.required=true;signingInput.autocomplete="new-password";
    const submit=brokerEl("button","Save Robinhood connection");
    submit.type="submit";
    setup.append(keyLabel,keyInput,signingLabel,signingInput,submit);
    function showStatus(data){
      accountDetails.replaceChildren();
      if(data.connected){
        health.textContent="Robinhood API connected · authenticated account access · live order execution not yet enabled";
        setup.hidden=true;
        for(const a of (data.accounts||[])){
          brokerRow(accountDetails,"Account "+a.account_number,
            "Status: "+a.status+" · Buying power: "+
            (a.buying_power||"unavailable")+" "+(a.buying_power_currency||"")+" · API tradable: "+(a.is_api_tradable?"yes":"no"));
        }
      } else {
        health.textContent="Robinhood not connected · "+(data.reason||"Check credentials");
        setup.hidden=false;
      }
    }
    async function refreshStatus(){
      const data=await request("/api/robinhood/status");
      showStatus(data);
      if(typeof updateRobinhoodTile==="function")updateRobinhoodTile(data);
    }
    setup.addEventListener("submit",async(event)=>{
      event.preventDefault();
      submit.disabled=true;
      try{
        await request("/api/robinhood/connect",{method:"POST",
          body:JSON.stringify({api_key:keyInput.value.trim(),private_key_b64:signingInput.value.trim()})});
        keyInput.value="";signingInput.value="";
        await refreshStatus();
      }catch(error){health.textContent="Robinhood connection error: "+error.message;}
      finally{keyInput.value="";signingInput.value="";submit.disabled=false;}
    });
    card.append(health,accountDetails,setup);
    refreshStatus().catch(()=>{health.textContent="Robinhood connection check unavailable";});
  }
  const actions=brokerEl("div",null,"broker-actions");
  actions.appendChild(brokerLink(broker.docs_url,"Official API requirements"));
  card.appendChild(actions);
  if(broker.id==="schwab")schwabInlineCard(card);
  return card;
}
async function loadBrokerWorkspace(){
  const status=document.getElementById("brokers-status");
  const grid=document.getElementById("broker-grid");
  if(!status||!grid)return;
  status.textContent="Refreshing broker capabilities…";
  try{
    const doc=await request("/api/brokers");
    if(!doc||doc.schema!==1||!Array.isArray(doc.brokers))
      throw Error("Broker capability service returned unexpected data");
    grid.replaceChildren(...doc.brokers.map(brokerCard));
    status.textContent=doc.brokers.length+" broker integrations listed · "+
      "Robinhood Crypto connection is checked separately. Live orders require explicit approval.";
  }catch(err){
    status.textContent="Broker status unavailable: "+err.message;
    grid.replaceChildren();
  }
}
document.addEventListener("DOMContentLoaded",()=>{
  const button=document.getElementById("brokers-refresh");
  if(button)button.addEventListener("click",()=>loadBrokerWorkspace());
});
