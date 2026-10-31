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
  const actions=brokerEl("div",null,"broker-actions");
  actions.appendChild(brokerLink(broker.docs_url,"Official API requirements"));
  if(broker.id==="schwab"){
    const a=brokerEl("a","Configure Schwab OAuth");
    a.href="/integrations.html#schwab-onboarding";
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
      "Schwab remains the only enabled live-order adapter. Other brokers are not connected.";
  }catch(err){
    status.textContent="Broker status unavailable: "+err.message;
    grid.replaceChildren();
  }
}
document.addEventListener("DOMContentLoaded",()=>{
  const button=document.getElementById("brokers-refresh");
  if(button)button.addEventListener("click",()=>loadBrokerWorkspace());
});
