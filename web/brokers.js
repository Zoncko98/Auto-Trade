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
function brokerCard(broker){
  const card=brokerEl("article",null,"broker-card");
  const heading=brokerEl("div",null,"broker-card-heading");
  const title=brokerEl("h2",broker.name);
  const live=broker.integration_status==="authorization_saved";
  const label=brokerEl("span",
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
  brokerRow(card,"Auto Trader connected?",broker.app_account_connected?
    "Saved authorization (revalidate with broker before orders)":"No");
  brokerRow(card,"Auto Trader live orders",broker.app_orders_supported?
    "Existing Schwab worker only; live permission is a separate step":
    "Not implemented / disabled");
  card.appendChild(brokerEl("p",broker.setup_requirement,"broker-note"));
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
  if(broker.id==="schwab"){
    const a=brokerEl("a","Configure Schwab OAuth");
    a.href="/broker-schwab.html#schwab-settings";
    actions.appendChild(a);
  }
  card.appendChild(actions);
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
