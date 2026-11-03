"use strict";

const $ = (id) => document.getElementById(id);
const money = (v) => new Intl.NumberFormat("en-US", {style:"currency",currency:"USD",minimumFractionDigits:2,maximumFractionDigits:2}).format(Number(v)||0);
const intNum = (v) => new Intl.NumberFormat("en-US").format(Number(v)||0);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
const pct = (v) => `${Number(v)||0}%`;
let csrf = null;
let status = null;
let activeView = "workspaces";
let activeWorkspace = "live";
const AVAILABLE_WORKSPACES = Object.freeze(["live","paper","robinhood_crypto","webull"]);
let robinhoodTileRefreshId=0;
let webullTileRefreshId=0;
let verifiedBrokerRequestId=0;
// Do not format missing numbers as $0.00, and never render stale broker
// snapshots as current. Values are only read from authenticated APIs.
function finiteUsd(value){
  if(typeof value!=="number" || !Number.isFinite(value) || Math.abs(value)>1e15)
    return null;
  return money(value);
}
function schwabEquityUsd(value){
  // Only Schwab's live worker emits Decimal equity as string.
  if(typeof value==="string"){
    if(!/^-?(?:0|[1-9]\d*)(?:\.\d{1,8})?$/.test(value))return null;
    value=Number(value);
  }
  return finiteUsd(value);
}
function updateWorkspaceBalances(paper,live){
  const paperLabel=$("workspace-paper-balance");
  const schwabLabel=$("workspace-schwab-balance");
  if(paperLabel){
    const equity=finiteUsd(paper?.account?.equity);
    paperLabel.textContent=equity===null?"Balance unavailable":"Sim. equity "+equity;
    paperLabel.title=equity===null?"Paper simulator balance unavailable":"Paper simulator equity, not real cash";
  }
  if(schwabLabel){
    const account=live?.account;
    const rawTime=account?.at;
    const timestamp=typeof rawTime==="string"?Date.parse(rawTime):NaN;
    // Fresh broker-reported equity only. A token or historical account cache
    // alone must never produce a 'current balance' tile.
    const age=Date.now()-timestamp;
    const fresh=live?.worker_online===true && Number.isFinite(timestamp) &&
      age>=-60000 && age<=300000;
    const equity=fresh?schwabEquityUsd(account?.equity):null;
    const lastReported=schwabEquityUsd(account?.equity);
    schwabLabel.textContent=equity!==null?"Equity "+equity:
      lastReported!==null && Number.isFinite(timestamp)?
      "Last reported "+lastReported:"Balance unavailable";
    schwabLabel.title=equity!==null?
      "Current Schwab worker-reported equity, verified within the last five minutes":
      lastReported!==null?
      "Historical Schwab worker snapshot only; not current account equity. Refresh connection/worker.":
      "No verified Schwab equity snapshot available. Check Schwab authorization and live worker status.";
  }
}
function updateAccountActivity(paper,live){
  const latest=Array.isArray(live?.decisions)?live.decisions[0]:null;
  const paperDecision=paper?.runtime?.last_paper_decision||"NOT_SCANNED";
  const rows=[
    ["live", latest?
       "Latest: "+latest.decision.replaceAll("_"," ")+(latest.summary?" — "+latest.summary:""):
       live?.worker_online?"Worker online · last scan NOT VERIFIED; no decisions recorded":"Worker offline or no heartbeat"],
    ["paper", "Last scan: "+paperDecision.replaceAll("_"," ")+
       (paper?.runtime?.last_paper_symbol?" · "+paper.runtime.last_paper_symbol:"")+
       (paper?.runtime?.last_paper_reason?" · "+paper.runtime.last_paper_reason:"")+
       (paper?.runtime?.paper_feed_checked_at?" · "+new Date(paper.runtime.paper_feed_checked_at).toLocaleTimeString():"")+
       (Number.isFinite(paper?.runtime?.paper_quotes_available)?" · "+paper.runtime.paper_quotes_available+" ranked candidates":"")+
       (paper?.runtime?.shadow_momentum?.candidate?" · SHADOW: "+paper.runtime.shadow_momentum.candidate.symbol+" "+
         paper.runtime.shadow_momentum.candidate.momentum_pct+"% momentum (no order)":
         " · SHADOW: no qualifying momentum trade")]
  ];
  rows.push(["robinhood_crypto","Robinhood scanner operates independently; open account for verified signals and execution status"]);
  rows.forEach(([key,value])=>{
    const tile=document.querySelector('[data-workspace="'+key+'"]');
    if(!tile)return;
    let el=tile.querySelector(".agent-activity-summary");
    if(!el){
      el=document.createElement("p");
      el.className="agent-activity-summary";
      el.style.cssText="font-size:12px;line-height:1.5;margin:12px 0;color:#aecce7;overflow-wrap:anywhere";
      tile.append(el);
    }
    el.textContent=value.slice(0,300);
    el.setAttribute("role","status");
  });
}
// Authenticated broker accounts only: not worker uptime, cached tokens,
// paper funds, AI readiness or permission to send live orders.
function verifiedConnectedAccounts(schwab,robinhood,webull){
  const rows=[];
  const account=schwab?.account;
  const time=typeof account?.at==="string"?Date.parse(account.at):NaN;
  const age=Date.now()-time;
  const heartbeat=schwab?.heartbeat_age_sec;
  if(schwab?.worker_online===true && Number.isFinite(heartbeat) &&
     heartbeat>=0 && heartbeat<=120 && Number.isFinite(time) &&
     age>=-60000 && age<=300000 && schwabEquityUsd(account?.equity)!==null){
    rows.push({name:"Schwab",detail:"Fresh broker account snapshot; not trading authorization"});
  }
  const activeRobinhood=robinhood?.connected===true &&
    Array.isArray(robinhood.accounts) &&
    robinhood.accounts.some(a=>typeof a?.account_number==="string" &&
      a.account_number.trim().length>0 && a.account_number.toLowerCase()!=="unknown" &&
      typeof a.status==="string" && a.status.toLowerCase()==="active");
  if(activeRobinhood){
    rows.push({name:"Robinhood Crypto",detail:"Authenticated active crypto account; order permission separate"});
  }
  const authenticatedWebull=webull?.connected===true && Array.isArray(webull.accounts) &&
    webull.accounts.some(a=>typeof a?.account_id==="string" && a.account_id.trim().length>0);
  if(authenticatedWebull){
    const sandbox=webull.environment==="sandbox";
    rows.push({name:sandbox?"Webull (sandbox)":"Webull",
      detail:sandbox?"Authenticated Webull sandbox account; live orders disabled":
        "Authenticated Webull account; Auto Trader live execution separately controlled"});
  }
  return rows;
}
function renderVerifiedConnectedAccounts(rows){
  const panel=$("verified-brokers"), list=$("verified-broker-items");
  if(!panel||!list)return;
  list.replaceChildren();
  for(const account of rows){
    const item=document.createElement("div");
    item.className="verified-broker";
    item.title=account.detail;
    const dot=document.createElement("span");
    dot.className="verified-broker-dot";
    dot.setAttribute("aria-hidden","true");
    const name=document.createElement("span");
    name.textContent=account.name;
    item.append(dot,name);
    list.append(item);
  }
  panel.classList.toggle("hidden",rows.length===0);
}
function clearVerifiedConnectedAccounts(){
  verifiedBrokerRequestId++; // Prevent stale in-flight auth lookups after sign-out.
  renderVerifiedConnectedAccounts([]);
}
async function refreshVerifiedConnectedAccounts(){
  const id=++verifiedBrokerRequestId;
  const responses=await Promise.allSettled([
    request("/api/live"),request("/api/robinhood/status"),request("/api/webull/status")
  ]);
  if(id!==verifiedBrokerRequestId||!csrf)return;
  const data=responses.map(r=>r.status==="fulfilled"?r.value:null);
  renderVerifiedConnectedAccounts(verifiedConnectedAccounts(...data));
  if(data[2])updateWebullTile(data[2]);
  else updateWebullTile({check_failed:true});
}

function clearWorkspaceBalances(){
  // Invalidate in-flight authenticated Robinhood portfolio responses on sign-out.
  robinhoodTileRefreshId++;
  webullTileRefreshId++;
  webullEquityRequestId++;
  if(typeof document.querySelector==="function")updateWebullTile({});
  const rh=$("workspace-robinhood-balance"), note=$("workspace-robinhood-value-note");
  if(rh){rh.textContent="Account value unavailable";rh.title="Sign in to view verified Robinhood holdings and USD buying power";}
  if(note)note.textContent="Holdings + USD buying power · verification required";
  for(const name of ["paper","schwab"]){
    const el=$("workspace-"+name+"-balance");
    if(el){el.textContent="Balance unavailable";el.title="Sign in and refresh to view available equity";}
  }
}
function selectWorkspace(workspace){
  if(!AVAILABLE_WORKSPACES.includes(workspace))return false;
  activeWorkspace=workspace;
  return true;
}
function webullAccountVerified(data){
  return data?.connected===true && Array.isArray(data.accounts) &&
    data.accounts.some(a=>typeof a?.account_id==="string" &&
      a.account_id.trim().length>0 && a.account_id.toLowerCase()!=="unknown");
}
let webullEquityRequestId=0;
function verifiedWebullUsd(raw){
  if(typeof raw!=="string"||!/^(?:0|[1-9]\d*)(?:\.\d{1,8})?$/.test(raw))return null;
  const value=Number(raw);
  return Number.isFinite(value)&&value<=1e12?value:null;
}
async function refreshWebullEquity(accounts){
  const id=++webullEquityRequestId;
  const results=await Promise.allSettled(accounts.map(a=>
    request("/api/webull/portfolio?account_id="+encodeURIComponent(a.account_id))));
  if(id!==webullEquityRequestId||!csrf)return;
  let sum=0,valid=0;
  for(const result of results){
    if(result.status!=="fulfilled")continue;
    const balance=result.value?.balances;
    if(balance?.total_asset_currency!=="USD")continue;
    const equity=verifiedWebullUsd(balance.total_net_liquidation_value);
    if(equity===null)continue;
    sum+=equity;valid++;
  }
  const main=$("workspace-webull-balance"),detail=$("workspace-webull-detail");
  if(!main||!detail)return;
  if(valid===accounts.length&&valid>0){
    main.textContent="Equity "+money(sum);
    detail.textContent=(valid===1?"1 verified account":valid+" verified accounts")+
      " · broker-reported USD net liquidation value · live orders disabled";
  }else{
    main.textContent="Equity unavailable";
    detail.textContent=valid+" of "+accounts.length+
      " account balances verified · open Webull for details · live orders disabled";
  }
}
const WORKSPACE_ORDER_KEY="auto-trader.workspace-order.v1";
const WORKSPACE_DEFAULT_ORDER=["live","paper","robinhood_crypto","webull"];
function workspaceOrder(){
  try{
    const raw=JSON.parse(localStorage.getItem(WORKSPACE_ORDER_KEY));
    return Array.isArray(raw)&&raw.length===4&&new Set(raw).size===4&&
      raw.every(x=>WORKSPACE_DEFAULT_ORDER.includes(x))?raw:WORKSPACE_DEFAULT_ORDER;
  }catch(_){return WORKSPACE_DEFAULT_ORDER;}
}
function applyWorkspaceOrder(){
  const grid=document.querySelector(".workspace-tile-grid");
  if(!grid||typeof grid.querySelectorAll!=="function")return;
  const order=workspaceOrder();
  [...grid.querySelectorAll("[data-workspace]")].sort((a,b)=>
    order.indexOf(a.dataset.workspace)-order.indexOf(b.dataset.workspace))
    .forEach(tile=>grid.appendChild(tile));
}
function saveWorkspaceOrder(order){
  try{localStorage.setItem(WORKSPACE_ORDER_KEY,JSON.stringify(order));}catch(_){}
  applyWorkspaceOrder();
}
function initWorkspaceSorting(){
  if(typeof document.querySelector!=="function" || typeof MutationObserver!=="function")return;
  const grid=document.querySelector(".workspace-tile-grid");
  if(!grid)return;
  let dragging=null,justDragged=false;
  const prepare=()=>{
    grid.querySelectorAll("[data-workspace]").forEach(tile=>{
      tile.draggable=true;
      tile.title="Drag to rearrange, or use Alt + arrow keys. Click to open.";
    });
  };
  prepare();
  new MutationObserver(prepare).observe(grid,{childList:true});
  grid.addEventListener("dragstart",e=>{
    const tile=e.target.closest("[data-workspace]");
    if(!tile)return;
    dragging=tile.dataset.workspace;
    e.dataTransfer.effectAllowed="move";
    e.dataTransfer.setData("text/plain",dragging);
    tile.classList.add("workspace-dragging");
  });
  grid.addEventListener("dragover",e=>{
    if(!dragging)return;
    const target=e.target.closest("[data-workspace]");
    if(!target||target.dataset.workspace===dragging)return;
    e.preventDefault();e.dataTransfer.dropEffect="move";
    target.classList.add("workspace-drop-target");
  });
  grid.addEventListener("dragleave",e=>{
    e.target.closest("[data-workspace]")?.classList.remove("workspace-drop-target");
  });
  grid.addEventListener("drop",e=>{
    const target=e.target.closest("[data-workspace]");
    if(!dragging||!target)return;
    e.preventDefault();
    const order=[...workspaceOrder()];
    const from=order.indexOf(dragging),to=order.indexOf(target.dataset.workspace);
    if(from>=0&&to>=0){order.splice(from,1);order.splice(to,0,dragging);saveWorkspaceOrder(order);}
    justDragged=true;dragging=null;
    grid.querySelectorAll(".workspace-drop-target,.workspace-dragging").forEach(t=>
      t.classList.remove("workspace-drop-target","workspace-dragging"));
  });
  grid.addEventListener("dragend",()=>{
    dragging=null;
    grid.querySelectorAll(".workspace-drop-target,.workspace-dragging").forEach(t=>
      t.classList.remove("workspace-drop-target","workspace-dragging"));
  });
  grid.addEventListener("click",e=>{
    if(justDragged){e.preventDefault();e.stopImmediatePropagation();justDragged=false;}
  },true);
  grid.addEventListener("keydown",e=>{
    if(!e.altKey||!["ArrowLeft","ArrowRight"].includes(e.key))return;
    const tile=e.target.closest("[data-workspace]");if(!tile)return;
    e.preventDefault();e.stopPropagation();
    const order=[...workspaceOrder()],i=order.indexOf(tile.dataset.workspace);
    const j=i+(e.key==="ArrowLeft"?-1:1);
    if(i<0||j<0||j>=order.length)return;
    [order[i],order[j]]=[order[j],order[i]];
    saveWorkspaceOrder(order);tile.focus();
  });
  $("workspace-reset-order")?.addEventListener("click",()=>{
    saveWorkspaceOrder(WORKSPACE_DEFAULT_ORDER);
  });
  applyWorkspaceOrder();
}

function positionWebullTile(verified){
  const tile=document.querySelector('[data-workspace="webull"]');
  const active=document.querySelector(".workspace-tile-grid");
  const upcoming=document.querySelector(".workspace-upcoming-grid");
  if(!tile||!active||!upcoming)return;
  const target=verified?active:upcoming;
  if(tile.parentElement!==target){target.appendChild(tile);applyWorkspaceOrder();}
  tile.classList.toggle("workspace-tile-featured",verified);
  tile.classList.toggle("workspace-tile-compact",!verified);
  const label=tile.querySelector(".workspace-tile-equity-label");
  if(label)label.hidden=!verified;
}
function updateWebullTile(data){
  const tile=typeof document.querySelector==="function"?
    document.querySelector('[data-workspace="webull"]'):null;
  const statusNode=$("workspace-webull-status");
  const main=$("workspace-webull-balance"),detail=$("workspace-webull-detail");
  if(!tile||!statusNode||!main||!detail)return;
  const accounts=Array.isArray(data?.accounts)?data.accounts.filter(a=>
    typeof a?.account_id==="string" && a.account_id.trim() &&
    a.account_id.toLowerCase()!=="unknown"):[];
  const verified=webullAccountVerified(data);
  positionWebullTile(verified);
  if(verified){
    const sandbox=data.environment==="sandbox";
    const types=[...new Set(accounts.map(a=>a.account_type).filter(x=>typeof x==="string" && x.trim()))];
    main.textContent=accounts.length+" verified "+(accounts.length===1?"account":"accounts")+" · checking equity…";
    detail.textContent=(types.length?types.join(", ")+" · ":"")+"Verified · fetching broker equity · live orders disabled";
    refreshWebullEquity(accounts);
    statusNode.textContent=sandbox?"SANDBOX · ACCOUNT VERIFIED":"ACCOUNT VERIFIED";
    tile.title="Webull account verified; automated live orders disabled";
    tile.setAttribute("aria-label","Open verified Webull account workspace");
  }else{
    main.textContent="Account access unverified";
    detail.textContent=data?.check_failed?"Connection check unavailable · retry refresh":
      data?.credentials_saved?"Credentials saved · complete account verification":
      "Set up Webull API credentials";
    statusNode.textContent=data?.check_failed?"CONNECTION CHECK FAILED":
      data?.credentials_saved?"CREDENTIALS SAVED · VERIFY":"SET UP WEBULL";
    tile.title="Open Webull account workspace to review connection";
    tile.setAttribute("aria-label","Open Webull account setup and connection status");
  }
  const count=$("workspace-active-count");
  if(count){
    const configured=[...document.querySelectorAll(".workspace-tile-grid .workspace-tile:not(.is-coming-soon)")].length;
    count.textContent="● "+configured+" available";
  }
}
async function refreshWebullTile(){
  const id=++webullTileRefreshId;
  webullEquityRequestId++;
  try{
    const data=await request("/api/webull/status");
    if(id!==webullTileRefreshId||!csrf)return;
    updateWebullTile(data);
  }catch(_){
    if(id!==webullTileRefreshId||!csrf)return;
    updateWebullTile({check_failed:true});
  }
}
function positionRobinhoodTile(configured){
  const tile=document.querySelector('[data-workspace="robinhood_crypto"]');
  const active=document.querySelector('.workspace-tile-grid');
  const upcoming=document.querySelector('.workspace-upcoming-grid');
  if(!tile||!active||!upcoming)return;
  const target=configured?active:upcoming;
  if(tile.parentElement!==target){target.appendChild(tile);applyWorkspaceOrder();}
  tile.classList.toggle("workspace-tile-featured",configured);
  tile.classList.toggle("workspace-tile-compact",!configured);
  const label=tile.querySelector(".workspace-tile-equity-label");
  if(label)label.hidden=!configured;
}
// Never equate buying power with account value. The portfolio endpoint
// includes all account USD buying power plus priced broker-reported holdings.
function robinhoodAccountValueUsd(raw){
  if(typeof raw!=="string" ||
     !/^(?:0|[1-9]\d*)(?:\.\d+)?$/.test(raw))return null;
  const value=Number(raw);
  return Number.isFinite(value)&&value<=1e12?money(value):null;
}
function updateRobinhoodTilePortfolio(portfolio){
  const amount=$("workspace-robinhood-balance");
  const note=$("workspace-robinhood-value-note");
  if(!amount)return;
  const formatted=portfolio?.available===true?
    robinhoodAccountValueUsd(portfolio.estimated_crypto_account_value_usd):null;
  if(formatted!==null){
    amount.textContent=formatted;
    amount.title="Estimated Robinhood Crypto account value: priced holdings + verified USD buying power. Indicative bid/ask marks, not liquidation proceeds.";
    if(note)note.textContent="Holdings + USD buying power · indicative estimate";
  }else{
    amount.textContent="Account value unavailable";
    const unpriced=Array.isArray(portfolio?.unpriced_holdings)?portfolio.unpriced_holdings:[];
    const reason=unpriced.length?
      "Unpriced Robinhood holdings: "+unpriced.join(", "):
      "Complete verified Robinhood holdings, prices or USD buying power unavailable";
    amount.title=reason+"; no total account value asserted.";
    if(note)note.textContent=unpriced.length?
      "Some holdings lack verified quotes":"Unable to verify complete holdings + USD balance";
  }
}
function updateRobinhoodTile(result){
  const accounts=Array.isArray(result.accounts)?result.accounts:[];
  const configured=result.credentials_saved===true||result.connected===true;
  positionRobinhoodTile(configured);
  const statusNode=$("workspace-robinhood-status");
  const amountNode=$("workspace-robinhood-balance");
  const note=$("workspace-robinhood-value-note");
  if(!statusNode||!amountNode)return;
  const verified=result.connected===true && accounts.length>0;
  statusNode.textContent=verified?
    (accounts.some(a=>a.is_api_tradable===true)?"ACCOUNT VERIFIED":"CONNECTED · RESTRICTED"):
    (configured?"CREDENTIALS SAVED · CHECK CONNECTION":"SET UP ROBINHOOD");
  amountNode.textContent=verified?"Checking account value…":"Account value unavailable";
  amountNode.title=verified?"Fetching verified holdings and USD buying power from Robinhood":
    "A verified Robinhood Crypto connection is required for an account valuation";
  if(note)note.textContent=verified?
    "Holdings + USD buying power · verifying quotes":
    "Holdings + USD buying power · verification required";
}
async function refreshRobinhoodTile(){
  const refreshId=++robinhoodTileRefreshId;
  try{
    const result=await request("/api/robinhood/status");
    if(refreshId!==robinhoodTileRefreshId)return;
    updateRobinhoodTile(result);
    if(result.connected===true&&Array.isArray(result.accounts)&&result.accounts.length){
      try{
        const portfolio=await request("/api/robinhood/portfolio");
        if(refreshId!==robinhoodTileRefreshId)return;
        updateRobinhoodTilePortfolio(portfolio);
      }catch(_){
        if(refreshId!==robinhoodTileRefreshId)return;
        // A valuation lookup failure does not mean broker auth failed.
        updateRobinhoodTilePortfolio({available:false});
      }
    }
  }catch(_){
    if(refreshId!==robinhoodTileRefreshId)return;
    const statusNode=$("workspace-robinhood-status");
    if(statusNode)statusNode.textContent="CONNECTION CHECK FAILED";
    updateRobinhoodTilePortfolio({available:false});
  }
}
async function loadWorkspaceAvailability() {
  try {
    const result=await request("/api/brokers");
    const schwab=Array.isArray(result.brokers)?
      result.brokers.find(item=>item.id==="schwab"):null;
    const label=$("workspace-schwab-status");
    if(label)label.textContent=schwab?.integration_status==="authorization_saved"?
      "AUTH SAVED":"NEEDS CONNECTION";
  } catch (_) {
    const label=$("workspace-schwab-status");
    if(label)label.textContent="STATUS UNAVAILABLE";
    // Schwab workspace remains navigable after a failed capability lookup.
  }
  await refreshRobinhoodTile();
  await refreshWebullTile();
}
function robinhoodEffective(data){
  const state=data.effective_state||"UNVERIFIED";
  const descriptions={PAUSED:"Paused",WORKER_OFFLINE:"Worker offline",
    RECONCILIATION_PENDING:"Reconciliation pending",ORDER_PENDING:"Order pending",
    RISK_BLOCKED:"Risk blocked",AI_VETO:"AI veto",
    NEWS_EVIDENCE_MISSING:"Relevant news missing",
    AI_UNAVAILABLE:"AI service unavailable",
    AI_REVIEW_BLOCKED:"AI/news review blocked",
    ARMED_WAITING_SIGNAL:"Armed · waiting for signal"};
  return {label:descriptions[state]||state.replaceAll("_"," "),
    detail:data.effective_detail||"Latest worker status unavailable",
    armed:data.policy_enabled===true,state};
}
function formatAge(seconds){
  if(!Number.isFinite(seconds)||seconds<0)return "age unavailable";
  if(seconds<60)return Math.floor(seconds)+" sec";
  if(seconds<3600)return Math.floor(seconds/60)+" min";
  return Math.floor(seconds/3600)+"h "+Math.floor((seconds%3600)/60)+"m";
}
function renderRobinhoodExternalHoldings(data){
  const worker=data?.worker||{};
  const checks=Array.isArray(worker.external_holding_reconciliation)?
    worker.external_holding_reconciliation:[];
  const closed=Array.isArray(worker.external_closed_positions)?
    worker.external_closed_positions:[];
  const el=$("rh-external-holdings-status");
  if(!el)return;
  el.textContent=(checks.length?checks.map(x=>(x.status||"unknown")+
    (Array.isArray(x.unmatched)&&x.unmatched.length?
      " (unmatched: "+x.unmatched.join(", ")+")":"")).join(" | "):
    "No broker holdings reconciliation recorded")+
    (closed.length?" · Confirmed externally closed bot inventory: "+
      closed.map(x=>(x.symbol||"?")+" "+(x.quantity||"unknown")+
        " units, broker remainder "+(x.broker_remaining_quantity||"0")+
        ", sale "+(x.filled_at||"time unavailable")).join(" | "):
      " · No documented external sale adjustments");
}
function renderRobinhoodScanDiagnostics(data){
  const worker=data?.worker||{};
  const source=$("rh-scan-source"),coverage=$("rh-scan-coverage"),
        closest=$("rh-scan-closest"),reasons=$("rh-scan-reasons");
  if(source)source.textContent=(worker.market_data_source||"unavailable")+
    " · Coinbase "+(worker.coinbase_feed||"unavailable")+
    " · "+(worker.coinbase_live_pairs??"unknown")+" fresh Coinbase pairs";
  if(coverage)coverage.textContent=(worker.quotes_checked??"unknown")+"/"+
    (worker.pairs_checked??"unknown")+" quotes checked · "+
    (worker.coinbase_scanned_pairs??"unknown")+" using Coinbase";
  const top=Array.isArray(worker.top_entry_observations)?worker.top_entry_observations:[];
  if(closest)closest.textContent=top.length?top.map(x=>
    (x.symbol||"?")+" "+(x.momentum_pct==null?"n/a":x.momentum_pct+"%")+
    " · "+(x.signal_reason||x.signal||"no reason")).join(" | "):
    "No momentum observations available";
  if(reasons)reasons.textContent=worker.signal_diagnostics||"No per-symbol diagnostics were recorded";
}
function renderRobinhoodPendingOrder(data){
  const panel=$("rh-pending-order-panel");
  const rows=Array.isArray(data.pending_orders)?data.pending_orders:[];
  if(!panel)return;
  if(!rows.length){
    panel.classList.add("hidden");
    return;
  }
  panel.classList.remove("hidden");
  const order=rows[0]||{};
  $("rh-pending-symbol").textContent=(order.symbol||"Unknown")+" · "+String(order.side||"unknown").toUpperCase();
  $("rh-pending-size").textContent=(order.quantity||"unknown")+" @ limit "+(order.limit_price||"unknown");
  $("rh-pending-local").textContent=(order.local_status||"unknown")+" · "+
    (order.age_seconds==null?"age unavailable":formatAge(Number(order.age_seconds)));
  $("rh-pending-broker").textContent=order.broker_matched?
    "Matched · "+(order.broker_state||"state unavailable"):
    "Not matched · "+(order.broker_lookup_detail||"Robinhood record not found");
  $("rh-pending-fill").textContent=
    "Filled qty: "+(order.filled_asset_quantity??"not reported")+
    " · Avg price: "+(order.average_price??"not reported")+
    " · Broker updated: "+(order.broker_updated_at||order.broker_created_at||"not reported");
  $("rh-pending-ids").textContent=
    "Client: "+(order.client_order_id||"unavailable")+
    " · Robinhood: "+(order.broker_order_id||"unavailable");
  $("rh-pending-detail").textContent=order.broker_matched?
    "Auto Trader will keep the order lock until this broker state is final and required fill fields are reconciled.":
    "Auto Trader has a durable local intent but cannot currently match it to a Robinhood order. "+
    "Successful broker-history misses: "+(order.reconcile_miss_count??0)+
    ". Automatic legacy recovery uses repeated successful misses plus a verified age window. "+
    "Manual resolution performs one more fresh Robinhood history check before releasing the lock.";
  const resolve=$("rh-pending-resolve");
  if(resolve){
    const eligible=order.manual_resolution_eligible===true;
    resolve.classList.toggle("hidden",!eligible);
    resolve.disabled=!eligible;
    resolve.dataset.clientOrderId=eligible?(order.client_order_id||""):"";
  }
}
async function resolveRobinhoodPendingOrder(){
  const button=$("rh-pending-resolve");
  const clientOrderId=button?.dataset.clientOrderId||"";
  if(!clientOrderId)throw Error("Pending orphan is not eligible for manual resolution");
  const original=button.textContent;
  button.disabled=true;
  button.textContent="Verifying Robinhood…";
  try{
    const result=await request("/api/robinhood/pending/resolve",{
      method:"POST",body:JSON.stringify({client_order_id:clientOrderId})
    });
    toast(result.reason||"Pending order lock resolved");
    await loadRobinhoodDecisionEvidence();
    await loadRobinhoodWorkspace().catch(()=>{});
  }finally{
    button.textContent=original;
    button.disabled=false;
  }
}
function renderRobinhoodAIReview(data){
  const worker=data?.worker||{};
  const outcomes=Array.isArray(worker.ai_candidate_reviews)?worker.ai_candidate_reviews:[];
  const outcome=$("rh-ai-outcome"),duration=$("rh-ai-duration"),
        classifier=$("rh-ai-classifier"),details=$("rh-ai-candidate-explanations");
  if(outcome)outcome.textContent=worker.ai_review_status||"No AI review recorded";
  if(duration)duration.textContent=worker.ai_review_duration_seconds==null?
    "No review timed":"Total "+Number(worker.ai_review_duration_seconds).toFixed(1)+" seconds"+
    " · Ollama request timeout 150 s · technical signal TTL 90 s, refreshed if needed";
  const withModel=outcomes.find(x=>x.model);
  const failedModel=outcomes.some(x=>x.outcome==="AI_UNAVAILABLE");
  if(classifier)classifier.textContent=withModel?
    (withModel.model+" · "+(withModel.classifier_model_source||"selected")):
    (failedModel?"Model request attempted but response unavailable":
     "Model not invoked on this scan");
  if(details)details.textContent=outcomes.length?
    outcomes.map(x=>(x.symbol||"Unknown")+" · "+(x.outcome||"unknown")+" · "+
      (Number(x.elapsed_seconds)||0).toFixed(1)+" s · "+
      (x.model||"no model invoked")+" · "+(x.reason||"No reason")).join(" | "):
    "No qualified technical entry candidate required news review in this scan.";
}
async function loadRobinhoodDecisionEvidence(){
  const data=await request("/api/robinhood/status");
  const effective=robinhoodEffective(data);
  $("rh-decision-status").textContent=effective.label+" · "+effective.detail;
  $("rh-ai-connectivity").textContent="Shared Ollama: "+
    (data.worker?.ai_connection_status||"not checked")+" · Model: "+
    (data.worker?.ai_model||"not invoked")+
    " · Workstation selection: "+(data.worker?.ai_selected_model||"unavailable")+
    " · AI gate: "+(data.worker?.ai_review_status||"not evaluated");
  renderRobinhoodAIReview(data);
  renderRobinhoodExternalHoldings(data);
  renderRobinhoodScanDiagnostics(data);
  renderRobinhoodPendingOrder(data);
  const rows=Array.isArray(data.decision_evidence)?data.decision_evidence:[];
  $("rh-decision-rows").innerHTML=rows.length?rows.slice().reverse().map(x=>
    "<tr><td>"+esc(x.at||"—")+"</td><td>"+esc(x.signal||"—")+
    "</td><td>"+esc(x.ai_review_status||"—")+
    (x.ai_review_duration_seconds==null?"":" · "+esc(Number(x.ai_review_duration_seconds).toFixed(1))+" s")+
    "</td><td>"+esc(x.ai_model||"—")+
    "</td><td>"+esc(x.ai_reason||"—")+"</td><td>"+esc(x.execution_status||"—")+
    (x.execution_reason?" · "+esc(x.execution_reason):"")+
    (x.exit_candidate_symbol?" · Exit "+esc(x.exit_candidate_symbol)+
      " momentum "+esc(x.exit_momentum_pct??"unknown")+"%, spread "+
      esc(x.exit_spread_pct??"unknown")+"%":"")+
    (x.entry_candidate_symbol?" · Entry "+esc(x.entry_candidate_symbol)+
      " momentum "+esc(x.entry_momentum_pct??"unknown")+"%":"")+
    "</td></tr>").join(""):'<tr><td colspan="6">No Robinhood worker decisions recorded yet</td></tr>';
}
async function loadRobinhoodExtras(){
  const status=await request("/api/robinhood/status");
  const effective=robinhoodEffective(status);
  $("rh-forecast-status").textContent=effective.label+" · "+effective.detail+
    " · Last scan: "+(status.worker?.updated_at||"unavailable")+
    " · Last signal: "+(status.worker?.last_signal||"no signal");
}
async function loadRobinhoodRisk(){
  const [policy,broker]=await Promise.all([
    request("/api/robinhood/risk"),request("/api/robinhood/status")]);
  const select=$("robinhood-risk-account");
  select.replaceChildren();
  const accounts=Array.isArray(broker.accounts)?broker.accounts:[];
  for(const a of accounts.filter(x=>x.is_api_tradable===true&&x.status==="active")){
    const option=document.createElement("option");
    option.value=a.account_number;
    option.textContent="Robinhood Crypto · "+a.account_number;
    select.append(option);
  }
  if(policy.account)select.value=policy.account;
  $("robinhood-risk-max").value=policy.max_order_usd||"5";
  $("robinhood-risk-exposure").value=policy.max_total_exposure_usd||"25";
  $("robinhood-risk-daily-loss").value=policy.max_daily_loss_usd||"5";
  $("robinhood-risk-positions").value=policy.max_open_positions??3;
  $("robinhood-risk-hold").value=policy.min_hold_minutes??15;
  $("robinhood-risk-profit").value=policy.min_profit_pct||"1";
  $("robinhood-risk-stop").value=policy.stop_loss_pct||"2";
  $("robinhood-risk-fee-buffer").value=policy.fee_buffer_pct||"0.25";
  $("robinhood-risk-cooldown").value=policy.reentry_cooldown_minutes??30;
  $("robinhood-risk-minimum").textContent=
    Number(policy.verified_broker_minimum_usd)>0?
    money(Number(policy.verified_broker_minimum_usd)):"Not verified";
  $("robinhood-risk-enabled").textContent=policy.enabled===true?"ON":"OFF";
  $("robinhood-risk-activate").checked=policy.enabled===true;
  const effective=robinhoodEffective(broker);
  $("robinhood-risk-feedback").textContent=effective.label+" · "+effective.detail+" · "+
    (policy.configured?"Saved risk settings loaded":"No risk policy saved");
  $("robinhood-risk-form").dataset.effectiveState=effective.state;

}
async function saveRobinhoodRisk(event){
  event.preventDefault();
  const button=event.currentTarget.querySelector('button[type="submit"]');
  button.disabled=true;
  try{
    const payload={account:$("robinhood-risk-account").value,
      max_order_usd:$("robinhood-risk-max").value,
      max_total_exposure_usd:$("robinhood-risk-exposure").value,
      max_daily_loss_usd:$("robinhood-risk-daily-loss").value,
      max_open_positions:Number($("robinhood-risk-positions").value),
      min_hold_minutes:Number($("robinhood-risk-hold").value),
      min_profit_pct:$("robinhood-risk-profit").value,
      stop_loss_pct:$("robinhood-risk-stop").value,
      fee_buffer_pct:$("robinhood-risk-fee-buffer").value,
      reentry_cooldown_minutes:Number($("robinhood-risk-cooldown").value),
      verified_broker_minimum_usd:"0",enabled:$("robinhood-risk-activate").checked};
    if(payload.enabled&&!window.confirm("Enable REAL-MONEY autonomous Robinhood crypto orders under these limits?"))return;
    await request("/api/robinhood/risk",{method:"POST",body:JSON.stringify(payload)});
    await loadRobinhoodRisk();
    toast("Robinhood trading permission updated: "+$("robinhood-risk-feedback").textContent);
  }catch(error){$("robinhood-risk-feedback").textContent=error.message;toast(error.message,true);}
  finally{button.disabled=false;}
}
function robinhoodNumber(value){
  if(value==null||value==="")return null;
  const n=Number(value);
  return Number.isFinite(n)?n:null;
}
function robinhoodCryptoPrice(value){
  const n=robinhoodNumber(value);
  if(n===null)return "Unavailable";
  if(n!==0&&Math.abs(n)<1e-12)return "$"+String(value);
  return "$"+new Intl.NumberFormat("en-US",{maximumFractionDigits:12,minimumFractionDigits:2}).format(n);
}
function robinhoodQuantity(value){
  const n=robinhoodNumber(value);
  return n===null?"Unavailable":
    new Intl.NumberFormat("en-US",{maximumFractionDigits:12}).format(n);
}
function robinhoodReturnUsd(value){
  const n=robinhoodNumber(value);
  if(n===null)return "Unavailable";
  const sign=n>0?"+":n<0?"−":"";
  const abs=Math.abs(n);
  const formatted=abs!==0&&abs<0.01?
    "$"+abs.toLocaleString("en-US",{minimumFractionDigits:4,maximumFractionDigits:8}):
    money(abs);
  return sign+formatted;
}
function robinhoodReturnPct(value){
  const n=robinhoodNumber(value);
  if(n===null)return "Unavailable";
  return (n>0?"+":n<0?"−":"")+Math.abs(n).toFixed(2)+"%";
}
function robinhoodDirection(value){
  const n=robinhoodNumber(value);
  return n===null?"":n>0?"pnl-up":n<0?"pnl-down":"pnl-flat";
}
function renderRobinhoodPortfolio(portfolio){
  const box=$("robinhood-positions-list");
  const status=$( "robinhood-positions-status");
  if(box)box.replaceChildren();
  if(!portfolio?.available){
    const message=portfolio?.reason||"Robinhood portfolio request unavailable";
    if(status)status.textContent=message;
    for(const id of ["rh-performance-value","rh-performance-pnl","rh-performance-pct","rh-pnl-coverage","rh-holdings-summary"]){
      const el=$(id);if(el)el.textContent="Unavailable";
    }
    if($("rh-performance-pnl-label"))$("rh-performance-pnl-label").textContent="Broker portfolio lookup failed";
    if($("rh-performance-disclosure"))$("rh-performance-disclosure").textContent=message;
    if(box)box.textContent=message;
    return;
  }
  const holdings=Array.isArray(portfolio.holdings)?portfolio.holdings:[];
  const covered=Number.isInteger(portfolio.pnl_covered_holdings)?portfolio.pnl_covered_holdings:0;
  const complete=portfolio.pnl_completeness==="complete_estimate";
  const amount=complete?portfolio.unrealized_pnl_usd:portfolio.known_unrealized_pnl_usd;
  const percent=complete?portfolio.unrealized_pnl_pct:portfolio.known_unrealized_pnl_pct;
  const value=$("rh-performance-value");
  if(value)value.textContent=portfolio.known_holdings_value_usd==null?
    "Unavailable":(portfolio.unpriced_holdings?.length?"Partial ":"")+
    money(portfolio.known_holdings_value_usd);
  for(const [id,raw,format] of [
    ["rh-performance-pnl",amount,robinhoodReturnUsd],
    ["rh-performance-pct",percent,robinhoodReturnPct]]){
    const el=$(id);
    if(!el)continue;
    el.textContent=raw==null?"Unavailable":format(raw);
    el.classList.remove("pnl-up","pnl-down","pnl-flat");
    const direction=robinhoodDirection(raw);
    if(direction)el.classList.add(direction);
  }
  const coverage=covered+" of "+holdings.length+" holdings have estimated P/L";
  if($("rh-pnl-coverage"))$("rh-pnl-coverage").textContent=coverage;
  if($("rh-holdings-summary"))$("rh-holdings-summary").textContent=
    holdings.length+" open holdings · "+covered+" with basis";
  if($("rh-performance-pnl-label"))$("rh-performance-pnl-label").textContent=
    complete?"Estimated on all holdings":"PARTIAL · "+coverage;
  if($("rh-performance-disclosure"))$("rh-performance-disclosure").textContent=
    "Estimated P/L is based on accessible broker fills reconciled to quantity, not Robinhood's official app average cost. "+
    "Fees, rewards, transfers, and missing history can affect results. This is since-purchase return, not today's move.";
  if(status)status.textContent=holdings.length+" holdings · "+covered+
    " estimated cost bases · "+(portfolio.order_count??"unknown")+" broker order records";
  if(!box)return;
  const intro=document.createElement("p");
  intro.className="panel-note";
  intro.textContent="USD buying power: "+(portfolio.cash_usd==null?"unavailable":money(portfolio.cash_usd))+
    " · Quotes are indicative midpoints, not executable sale prices.";
  box.append(intro);
  const table=document.createElement("table");
  table.className="rh-holdings-table";
  const head=document.createElement("thead");
  head.innerHTML="<tr><th>Asset</th><th>Quantity</th><th>Current price</th><th>Avg acquisition cost*</th><th>Market value</th><th>Unrealized P/L</th><th>P/L %</th></tr>";
  table.append(head);
  const body=document.createElement("tbody");
  for(const holding of holdings){
    const row=document.createElement("tr");
    const asset=document.createElement("td");
    const title=document.createElement("span");
    title.className="rh-asset-name";
    title.textContent=String(holding.symbol||"Unknown").replace(/-USD$/,"");
    const note=document.createElement("span");
    note.className="rh-subnote";
    note.textContent=holding.cost_basis_source==="estimated_broker_fill_history"?
      "Estimated fill-history basis":
      (holding.cost_basis_note||"Cost basis unavailable");
    asset.append(title,note);row.append(asset);
    const values=[
      robinhoodQuantity(holding.quantity),
      robinhoodCryptoPrice(holding.current_price_usd),
      holding.average_cost_usd==null?"Unavailable":robinhoodCryptoPrice(holding.average_cost_usd),
      holding.market_value_usd==null?"Unavailable":money(holding.market_value_usd),
      holding.unrealized_pnl_usd==null?"Unavailable":robinhoodReturnUsd(holding.unrealized_pnl_usd),
      holding.unrealized_pnl_pct==null?"Unavailable":
        (robinhoodNumber(holding.unrealized_pnl_pct)>0?"▲ ":
         robinhoodNumber(holding.unrealized_pnl_pct)<0?"▼ ":"")+
        robinhoodReturnPct(holding.unrealized_pnl_pct)
    ];
    values.forEach((value,i)=>{
      const cell=document.createElement("td");
      cell.textContent=value;
      if(i===2&&holding.average_cost_usd==null)cell.classList.add("rh-unavailable");
      if(i>=4){
        const cls=robinhoodDirection(holding.unrealized_pnl_usd);
        if(cls)cell.classList.add(cls);
        if(value==="Unavailable")cell.classList.add("rh-unavailable");
      }
      if(i===2)cell.title=holding.cost_basis_note||"Estimated from order fills";
      row.append(cell);
    });
    body.append(row);
  }
  if(!holdings.length){
    const row=document.createElement("tr");
    const cell=document.createElement("td");
    cell.colSpan=7;cell.textContent="No Robinhood Crypto holdings reported";
    row.append(cell);body.append(row);
  }
  table.append(body);box.append(table);
}
async function loadRobinhoodWorkspace(){
  const statusNode=$("robinhood-workspace-status");
  const accountsNode=$("robinhood-workspace-accounts");
  const tileStatus=$("workspace-robinhood-status");
  const balance=$("workspace-robinhood-balance");
  if(!statusNode||!accountsNode)return;
  statusNode.textContent="Checking Robinhood authentication…";
  try{
    const result=await request("/api/robinhood/status");
    accountsNode.replaceChildren();
    const accounts=Array.isArray(result.accounts)?result.accounts:[];
    updateRobinhoodTile(result);
    const worker=result.worker||{};
    const cashStat=$("robinhood-cash-stat");
    const accountStat=$("robinhood-account-stat");
    const usd=accounts.length===1?Number(accounts[0].buying_power):NaN;
    if(cashStat)cashStat.textContent=accounts.length===1&&accounts[0].buying_power_currency==="USD"&&
      accounts[0].buying_power!=null&&Number.isFinite(usd)?money(usd):"—";
    if(accountStat)accountStat.textContent=accounts.some(a=>a.is_api_tradable===true)?"ACTIVE":"UNVERIFIED";
    const executionMode=$("robinhood-execution-mode");
    const orderPermission=$("robinhood-order-permission");
    const executionPill=$("robinhood-execution-pill");
    const effective=robinhoodEffective(result);
    const permitted=effective.armed;
    if(executionMode)executionMode.textContent=effective.label;
    if(orderPermission)orderPermission.textContent=effective.label;
    if(executionPill)executionPill.textContent=effective.label.toUpperCase();
    const scanEl=$("robinhood-scanner-state");
    const marketFeed=$("robinhood-market-feed");
    if(marketFeed)marketFeed.textContent="Coinbase public WebSocket: "+(worker.coinbase_feed||"UNVERIFIED")+
      " · Live pairs: "+(worker.coinbase_live_pairs??0)+
      " · Current scan from Coinbase: "+(worker.coinbase_scanned_pairs??0)+
      " · Fallback: Robinhood signed quotes";
    const diag=$("robinhood-signal-diagnostics");
    if(diag)diag.textContent=worker.signal_diagnostics||"No per-pair diagnostics recorded";
    const orderEl=$("robinhood-order-state");
    const executionEl=$("robinhood-execution-state");
    const when=worker.updated_at?new Date(worker.updated_at):null;
    const lastSeen=when&&!Number.isNaN(when.getTime())?when.toLocaleString():"not reported";
    if(scanEl)scanEl.textContent="Worker: "+(worker.worker||"not started")+
      " · Quotes checked: "+(Number.isInteger(worker.quotes_checked)?worker.quotes_checked:"unavailable")+
      " / "+(Number.isInteger(worker.pairs_checked)?worker.pairs_checked:"?")+
      " · Broker-supported universe: "+(worker.universe_size??"unavailable")+
      " · Last checked: "+lastSeen+
      ". Quote checks are not trading signals.";
    if(orderEl){
      const pending=Array.isArray(result.pending_orders)?result.pending_orders:[];
      if(pending.length){
        const p=pending[0];
        orderEl.textContent="LOCKED · "+(p.symbol||"unknown")+" "+String(p.side||"").toUpperCase()+
          " · local "+(p.local_status||"unknown")+" · Robinhood "+
          (p.broker_matched?(p.broker_state||"state unavailable"):(p.broker_lookup_detail||"not matched"))+
          " · "+formatAge(Number(p.age_seconds));
      }else{
        orderEl.textContent="Unreconciled Auto Trader intents: "+
          (Number.isInteger(worker.pending_order_intents)?worker.pending_order_intents:"unavailable")+
          ". Broker historical orders are separate from bot-confirmed fills.";
      }
    }
    if(executionEl)executionEl.textContent=effective.detail+
      " · Worker status: "+(worker.execution_status||"unavailable")+
      " · Risk: "+(worker.risk_check||"unavailable")+
      " · Bot positions: "+(worker.bot_open_positions??"unavailable")+
      " · Daily realized P/L: "+(worker.daily_realized_pnl_usd==null?"unavailable":money(Number(worker.daily_realized_pnl_usd)))+
      " · Why: "+(worker.execution_reason||"Not yet recorded");
    const activityEl=$("robinhood-trade-activity");
    if(activityEl)activityEl.textContent=worker.last_order_confirmed?
      "Broker-confirmed bot fill recorded; inspect broker order history for details.":
      "No autonomous Robinhood fill verified. Broker historical orders do not prove bot execution.";
    const strategyEl=$("robinhood-strategy-status");
    if(strategyEl)strategyEl.textContent=
      "Scan: "+(worker.worker||"unavailable")+
      " · Signal: "+(worker.last_signal||"NOT_VERIFIED")+
      " · Trading permission: "+effective.label;
    const reconcileEl=$("robinhood-holdings-reconciliation");
    if(reconcileEl){
      const checks=Array.isArray(worker.external_holding_reconciliation)?
        worker.external_holding_reconciliation:[];
      const imported=Array.isArray(worker.external_closed_positions)?
        worker.external_closed_positions:[];
      reconcileEl.textContent=(checks.length?checks.map(x=>x.status||"unknown").join(" | "):
        "No broker reconciliation recorded")+
        (imported.length?" · Confirmed external sells: "+
          imported.map(x=>(x.symbol||"?")+" "+(x.quantity||"unknown")+" units").join(", "):"");
    }
    const riskEl=$("robinhood-risk-status");
    if(riskEl)riskEl.textContent="Account preflight: "+(worker.risk_check||"not reported")+
      " · Unreconciled intents: "+(Number.isInteger(worker.pending_order_intents)?worker.pending_order_intents:"unavailable")+
      ". Order-size and buying-power limits are enforced before authorization.";
    if(!result.connected||!accounts.length){
      const message=result.connected?"No crypto trading accounts returned":(result.reason||"Authentication unavailable");
      statusNode.textContent="Robinhood not ready: "+message;
      statusNode.title="No automated Robinhood strategy is connected. Credentials alone cannot execute trades.";

      const action=document.createElement("button");
      action.type="button";
      action.textContent="Open Robinhood connection settings";
      action.addEventListener("click",()=>showView("brokers"));
      accountsNode.append(action);
      return;
    }
    const ai=$("robinhood-ai-readiness");
    if(ai){
      request("/api/ai/readiness").then(d=>{
        ai.textContent="Shared AI provider: "+(d.provider||"not configured")+
          " · Model verification: "+(d.status||"unknown")+
          " · Crypto AI review: "+(worker.ai_review_status||"no candidate")+
          " · Model: "+(worker.ai_model||"not recorded");
      }).catch(()=>{ai.textContent="Shared AI model status unavailable";});
    }
    const positionState=$("robinhood-positions-status");
    if(positionState){
      positionState.textContent="Fetching Robinhood holdings and reconciled fill history…";
      request("/api/robinhood/portfolio").then(portfolio=>{
        renderRobinhoodPortfolio(portfolio);
        updateRobinhoodTilePortfolio(portfolio);
        if(portfolio.available){
          const holdings=Number.isInteger(portfolio.position_count)?portfolio.position_count:0;
          if($("robinhood-holdings-stat"))$("robinhood-holdings-stat").textContent=String(holdings);
          if($("robinhood-orders-stat"))$("robinhood-orders-stat").textContent=
            Number.isInteger(portfolio.order_count)?String(portfolio.order_count):"—";
          const total=$("robinhood-total-stat");
          if(total)total.textContent=portfolio.estimated_crypto_account_value_usd!=null?
            money(portfolio.estimated_crypto_account_value_usd):
            portfolio.known_holdings_value_usd!=null&&portfolio.cash_usd!=null?
            money(Number(portfolio.known_holdings_value_usd)+Number(portfolio.cash_usd))+"+":"Unavailable";
          const note=$("robinhood-total-note");
          if(note)note.textContent=portfolio.unpriced_holdings?.length?
            "Partial estimate · unpriced: "+portfolio.unpriced_holdings.join(", "):
            "Holdings + USD buying power; indicative quotes, not liquidation proceeds";
        }
      }).catch(error=>{
        updateRobinhoodTilePortfolio({available:false});
        renderRobinhoodPortfolio({
          available:false,reason:"Robinhood portfolio lookup unavailable: "+error.message});
      });
    }
    const eligible=accounts.some(a=>a.is_api_tradable===true);
    statusNode.title="Robinhood account eligibility and execution permission are reported independently.";
    const decisionNode=$("robinhood-ai-decisions");
    if(decisionNode)decisionNode.textContent=
      (worker.ai_review_status||"No AI evaluation recorded")+
      (worker.ai_model?" · "+worker.ai_model:"")+
      (worker.ai_reason?" · "+worker.ai_reason:"");
    statusNode.textContent=eligible?
      "Robinhood API account verified · "+effective.label+": "+effective.detail:
      "Robinhood account connected · API trading eligibility not confirmed";

    for(const a of accounts){
      const block=document.createElement("article");
      block.className="broker-card";
      const title=document.createElement("h3");
      title.textContent="Robinhood Crypto account "+a.account_number;
      const details=document.createElement("p");
      details.textContent="Account: "+a.status+" · Buying power: "+
        (a.buying_power||"unavailable")+" "+(a.buying_power_currency||"")+
        " · API tradable: "+(a.is_api_tradable?"yes":"not confirmed");
      block.append(title,details);
      accountsNode.append(block);
    }
  }catch(err){
    statusNode.textContent="Robinhood status unavailable: "+err.message;
    if(tileStatus)tileStatus.textContent="STATUS UNAVAILABLE";
  }
}
let page = {trades:1,reviews:1};
let pageData = {trades:null,reviews:null};
let refreshing = false;
let toastTimer = null;

function toast(text, error=false) {
  const box=$("toast");
  box.textContent=text;
  box.classList.remove("hidden");
  box.classList.toggle("error",error);
  clearTimeout(toastTimer);
  toastTimer=setTimeout(()=>box.classList.add("hidden"),4800);
}
async function request(url, options={}) {
  const headers = {"Accept":"application/json",...(options.headers||{})};
  if (options.body) headers["Content-Type"]="application/json";
  if (options.method && options.method!=="GET" && csrf) headers["X-CSRF-Token"]=csrf;
  let response;
  try { response=await fetch(url,{credentials:"same-origin",cache:"no-store",...options,headers}); }
  catch (_) { throw Error("Dashboard connection failed. Is the TrueNAS app running?"); }
  let payload={};
  try{payload=await response.json();}catch(_){}
  if (response.status===401 && !url.endsWith("/login")) {
    csrf=null; showLogin();
    throw Error("Session expired. Please sign in again.");
  }
  if(!response.ok) throw Error(payload.error || `HTTP ${response.status}`);
  return payload;
}
function showLogin(){
  clearVerifiedConnectedAccounts();
  clearWorkspaceBalances();
  $("app").classList.add("hidden");
  $("login-screen").classList.remove("hidden");
  $("password").value="";
  $("password").focus();
}
function showApp(){
  $("login-screen").classList.add("hidden");
  $("app").classList.remove("hidden");
  // Sign-in and restored sessions always land on the account overview.
  showView("workspaces");
  // Use the local installed version, not the remote GitHub release.
  loadWorkspaceAvailability().catch(()=>{});
  refreshVerifiedConnectedAccounts().catch(()=>{});
  request("/api/profile").then(profile=>{
    const version=profile.version;
    const label=$("sidebar-app-version");
    if(label)label.textContent=(typeof version==="string" &&
      /^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$/.test(version))?
      "Auto Trader · v"+version:"Auto Trader · Version unavailable";
  }).catch(()=>{
    const label=$("sidebar-app-version");
    if(label)label.textContent="Auto Trader · Version unavailable";
  });
}
async function init(){
  bindEvents();
  try {
    const session=await request("/api/session");
    csrf=session.csrf;
    showApp();
    await refreshAll();
    await checkForUpdate().catch(()=>{});
  } catch(_) { showLogin(); }
  setInterval(()=>{if(csrf) refreshAll().catch(err=>toast(err.message,true));},15000);
  setInterval(()=>{if(csrf) checkForUpdate().catch(()=>{});},60000);
  setInterval(()=>{if(csrf) refreshVerifiedConnectedAccounts().catch(()=>{});},30000);
}
function bindEvents(){
  $("login-form").addEventListener("submit", async (ev)=>{
    ev.preventDefault();
    const btn=ev.currentTarget.querySelector("button");
    btn.disabled=true;
    $("login-error").textContent="";
    try{
      const data=await request("/api/login",{method:"POST",body:JSON.stringify({username:$("username").value,password:$("password").value})});
      csrf=data.csrf;showApp();await refreshAll();await checkForUpdate().catch(()=>{});
    }catch(err){$("login-error").textContent=err.message;}finally{btn.disabled=false;}
  });
  $("profile-check-update").addEventListener("click",()=>checkForUpdate()
      .catch(err=>toast(err.message,true)));
  $("profile-password-form").addEventListener("submit",changeDashboardPassword);
  $("profile-webull-margin-form")?.addEventListener("submit",saveWebullMarginPreference);
  $("logout-btn").addEventListener("click",async()=>{
    try{await request("/api/logout",{method:"POST",body:"{}"});}catch(_){}
    csrf=null;showLogin();
  });
  $("refresh-btn").addEventListener("click",()=>{
    refreshAll().catch(err=>toast(err.message,true));
    refreshVerifiedConnectedAccounts().catch(()=>{});
  });
  document.querySelectorAll("[data-view]").forEach(button=>button.addEventListener("click",()=>showView(button.dataset.view)));
  document.querySelectorAll("[data-mode]").forEach(button=>button.addEventListener("click",()=>setMode(button.dataset.mode)));
  $("settings-form").addEventListener("submit",saveSettings);
  $("paper-service-toggle").addEventListener("click",togglePaperService);
  $("settings-form").querySelectorAll("input").forEach(field=>field.addEventListener("input",updatePreview));
  for(const kind of ["trades","reviews"]){
    $(kind+"-prev").addEventListener("click",()=>loadPage(kind,Math.max(1,page[kind]-1)));
    $(kind+"-next").addEventListener("click",()=>loadPage(kind,page[kind]+1));
  }
  $("export-trades").addEventListener("click",exportTrades);
  $("export-live-trades").addEventListener("click",()=>downloadWorkbook(
    "/api/live/export.xlsx","autotrader-live-trades.xlsx",$("export-live-trades")));
  $("export-live-evidence").addEventListener("click",()=>downloadWorkbook(
    "/api/live/export.xlsx","autotrader-live-evidence.xlsx",$("export-live-evidence")));
  $("robinhood-refresh")?.addEventListener("click",()=>loadRobinhoodWorkspace().catch(err=>toast(err.message,true)));
  $("robinhood-configure")?.addEventListener("click",()=>showView("brokers"));
  $("rh-pending-resolve")?.addEventListener("click",()=>resolveRobinhoodPendingOrder()
    .catch(err=>toast(err.message,true)));
  document.querySelectorAll(".workspace-tile:not(:disabled)").forEach(tile=>
    tile.addEventListener("click",()=>{
      if(!AVAILABLE_WORKSPACES.includes(tile.dataset.workspace))return;
      showView(tile.dataset.workspace==="paper"?"overview":
        tile.dataset.workspace==="robinhood_crypto"?"robinhood":
        tile.dataset.workspace==="webull"?"webull":"live");
    }));
  document.addEventListener("click",event=>{
    const live=event.target.closest("[data-export-live-index]");
    const paper=event.target.closest("[data-export-paper-index]");
    if(live){
      const index=Number(live.dataset.exportLiveIndex);
      downloadWorkbook("/api/live/export.xlsx?index="+index,
        "autotrader-live-trade-"+index+".xlsx",live);
    } else if(paper){
      const index=Number(paper.dataset.exportPaperIndex);
      downloadWorkbook("/api/paper/export.xlsx?index="+index,
        "autotrader-paper-trade-"+index+".xlsx",paper);
    }
  });
}
let operationsDecisions=[];
function opsRecord(title,fields){
  return '<article class="ops-record"><h3>'+esc(title)+'</h3>'+
    fields.map(([label,value])=>'<div class="ops-field"><span>'+esc(label)+'</span><strong>'+esc(value==null||value===""?"Unavailable":value)+'</strong></div>').join("")+'</article>';
}
function opsDate(value){
  if(!value)return "Not reported";
  const n=Date.parse(value);return Number.isFinite(n)?new Date(n).toLocaleString():"Invalid timestamp";
}
function opsSection(name){
  document.querySelectorAll("[data-ops-panel]").forEach(e=>e.classList.toggle("hidden",e.dataset.opsPanel!==name));
  document.querySelectorAll("[data-ops-section]").forEach(e=>e.classList.toggle("active",e.dataset.opsSection===name));
}
function opsInspect(){
  const i=Number($("ops-decision-select")?.value);
  const d=operationsDecisions[i];
  const box=$("ops-decision-detail");
  if(!box)return;
  if(!d){box.textContent="No decision selected.";return;}
  box.innerHTML=opsRecord(d.source+" · "+(d.symbol||d.signal||"Decision"),[
    ["Recorded at",opsDate(d.at)],["Signal",d.signal],["AI review",d.ai_review_status||d.decision],
    ["AI model",d.ai_model],["AI reasoning",d.ai_reason||d.summary],
    ["AI review seconds",d.ai_review_duration_seconds],
    ["Per-candidate AI evidence",Array.isArray(d.ai_candidate_reviews)?
      d.ai_candidate_reviews.map(x=>(x.symbol||"?")+": "+x.outcome+" / "+
        x.elapsed_seconds+"s / "+(x.model||"not invoked")+" / "+x.reason).join(" | "):null],
    ["Fresh signal revalidated after AI",d.entry_signal_revalidated],
    ["Entry candidate",d.entry_candidate_symbol],["Exit candidate",d.exit_candidate_symbol],
    ["Momentum",d.entry_momentum_pct??d.exit_momentum_pct],
    ["Spread",d.exit_spread_pct],["Market data",d.market_data_source],
    ["Coinbase feed",d.coinbase_feed],
    ["Quotes checked",d.quotes_checked==null?null:String(d.quotes_checked)+"/"+String(d.pairs_checked??"?")],
    ["Closest candidates",Array.isArray(d.top_entry_observations)?d.top_entry_observations.map(x=>
      (x.symbol||"?")+" "+(x.momentum_pct==null?"n/a":x.momentum_pct+"%")+
      " · "+(x.signal_reason||x.signal||"")).join(" | "):null],
    ["Scan diagnostics",d.signal_diagnostics],
    ["Execution state",d.execution_status||"Not reported"],
    ["Execution reason",d.execution_reason],["Broker fill","Not established by this decision record"]
  ]);
}
async function loadOperations(){
  const updated=$("ops-updated");if(updated)updated.textContent="Refreshing authenticated observations…";
  const sources=await Promise.allSettled([
    request("/api/status"),request("/api/live"),request("/api/robinhood/status"),request("/api/robinhood/portfolio")
  ]);
  const [paper,live,rh,portfolio]=sources.map(x=>x.status==="fulfilled"?x.value:null);
  const sourceNote=(v)=>v?"Loaded":"Unavailable / request failed";
  const worker=rh?.worker||{};
  const rhRows=Array.isArray(rh?.decision_evidence)?rh.decision_evidence:[];
  const liveRows=Array.isArray(live?.decisions)?live.decisions:[];
  operationsDecisions=[
    ...rhRows.map(x=>({...x,source:"Robinhood"})),
    ...liveRows.map(x=>({...x,source:"Schwab"}))
  ].sort((a,b)=>(Date.parse(b.at)||0)-(Date.parse(a.at)||0));
  const paperDecision=paper?.runtime?.last_paper_decision;
  const activity=[
    opsRecord("Schwab scanner",[
      ["Worker",live?live.worker_online===true?"Online":"Offline / not verified":"Unavailable"],
      ["Last recorded decision",liveRows[0]?.decision],["Explanation",liveRows[0]?.summary],
      ["Recorded decisions",live?String(liveRows.length):null]
    ]),
    opsRecord("Paper scanner · simulated",[
      ["Last decision",paperDecision],["Symbol",paper?.runtime?.last_paper_symbol],
      ["Reason",paper?.runtime?.last_paper_reason],
      ["Feed checked",opsDate(paper?.runtime?.paper_feed_checked_at)]
    ]),
    opsRecord("Robinhood crypto scanner",[
      ["Worker",worker.worker],["Last signal",worker.last_signal],
      ["AI review",worker.ai_review_status],["Reason",worker.execution_reason],
      ["Last update",opsDate(worker.updated_at)],["Quotes checked",worker.quotes_checked]
    ])
  ];
  $("ops-activity").innerHTML=activity.join("");
  const pending=Array.isArray(rh?.pending_orders)?rh.pending_orders:[];
  const orderCards=pending.map((x,i)=>opsRecord("Robinhood unresolved intent "+(i+1),[
    ["Symbol",x.symbol],["Side",x.side],["Local state",x.local_status],
    ["Broker match",x.broker_matched?"Matched":"Not confirmed"],
    ["Broker state",x.broker_state],["Broker lookup",x.broker_lookup_detail],
    ["Age",Number.isFinite(x.age_seconds)?formatAge(x.age_seconds):null]
  ]));
  $("ops-orders").innerHTML=opsRecord("Execution & reconciliation status",[
    ["Robinhood unresolved intents",rh?String(pending.length):null],
    ["Robinhood execution",worker.execution_status],["Last execution reason",worker.execution_reason],
    ["Schwab worker",live?live.worker_online===true?"Online":"Offline / unverified":null],
    ["Paper trade count · simulated",paper?.account?.trade_count],
    ["Broker-confirmed Robinhood bot fill",rh?worker.last_order_confirmed===true?"Reported":"Not verified":null]
  ])+orderCards.join("");
  const schwabAt=Date.parse(live?.account?.at||"");
  const fresh=live?.worker_online===true&&Number.isFinite(schwabAt)&&Date.now()-schwabAt>=-60000&&Date.now()-schwabAt<=300000;
  const schwabEquity=fresh?schwabEquityUsd(live?.account?.equity):null;
  const paperEquity=finiteUsd(paper?.account?.equity);
  const accounts=Array.isArray(rh?.accounts)?rh.accounts:[];
  const bp=accounts.length===1&&accounts[0].buying_power_currency==="USD"?finiteUsd(Number(accounts[0].buying_power)):null;
  $("ops-portfolio").innerHTML=[
    opsRecord("Schwab · live brokerage",[["Verified current equity",schwabEquity],["Last broker snapshot",opsDate(live?.account?.at)],["Status",fresh?"Fresh worker snapshot":"Not verified as current"]]),
    opsRecord("Robinhood · live crypto",[["USD buying power",rh?.connected?bp:null],["Broker-reported holdings",portfolio?.available?portfolio.position_count:null],["Account valuation","Open Robinhood workspace for holdings + quoted valuation"]]),
    opsRecord("Paper Trading · simulation",[["Simulated equity",paperEquity],["Simulated trade count",paper?.account?.trade_count],["Real brokerage funds","Not included"]])
  ].join("");
  const selector=$("ops-decision-select");
  if(selector){
    selector.replaceChildren();
    if(!operationsDecisions.length)selector.add(new Option("No recorded decisions available",""));
    operationsDecisions.slice(0,100).forEach((d,i)=>selector.add(new Option(
      d.source+" · "+(d.signal||d.decision||"Decision")+" · "+opsDate(d.at),String(i))));
    opsInspect();
  }
  if(updated)updated.textContent="Refreshed "+new Date().toLocaleString()+" · Schwab "+sourceNote(live)+" · Paper "+sourceNote(paper)+" · Robinhood "+sourceNote(rh)+" · Holdings "+sourceNote(portfolio);
}

let webullTraderPolicy=null;
let webullExecutionValidated=false;
function webullRow(root,key,value){
  const name=document.createElement("strong"),detail=document.createElement("span");
  name.textContent=key;detail.textContent=value==null?"Unavailable":String(value);
  const row=document.createElement("div");
  row.className="broker-detail-row";
  row.append(name,detail);
  root.append(row);
}
function webullPrice(raw){
  if(typeof raw!=="string" && typeof raw!=="number")return null;
  if(!/^-?(?:0|[1-9]\d*)(?:\.\d{1,8})?(?:[Ee][+-]?\d{1,3})?$/.test(String(raw)))return null;
  const n=Number(raw);
  return Number.isFinite(n)&&Math.abs(n)<1e13?money(n):null;
}
function webullReadableDate(raw){
  const dt=typeof raw==="string"?Date.parse(raw):NaN;
  return Number.isFinite(dt)?new Date(dt).toLocaleString():"Not reported";
}
function webullListRoot(id){const root=$(id);if(root)root.replaceChildren();return root;}
async function loadWebullTrader(){
  const data=await request("/api/webull/trader");
  const worker=data.worker||{},policy=data.policy||{};
  webullTraderPolicy=policy;
  const armed=false; // Do not infer live permission from saved policy and execution validation.
  const mode=$("webull-order-mode");
  if(mode){mode.textContent=data.execution_validated===true&&policy.enabled===true?"PERMISSION UNVERIFIED":"DISARMED";mode.className="mode-tag stopped";}
  const orders=$("webull-orders-count");
  if(orders)orders.textContent=Array.isArray(worker.pending_orders)?String(worker.pending_orders.length):"Unavailable";
  const root=webullListRoot("webull-engine-fields");
  const heartbeat=$("webull-worker-updated");
  const age=Date.now()-Date.parse(worker.updated_at||"");
  const fresh=Number.isFinite(age)&&age>=-60000&&age<600000;
  if(heartbeat)heartbeat.textContent=fresh?
    "Webull scanner last reported "+webullReadableDate(worker.updated_at):
    "Webull worker offline, stale or not yet verified";
  if(root){
    webullRow(root,"Scanner",fresh?worker.worker||"Unverified":"No recent worker heartbeat");
    webullRow(root,"Last order decision",worker.execution_status||"NO_WORKER_REPORT");
    webullRow(root,"AI approvals",Array.isArray(worker.ai_reviews)?
      worker.ai_reviews.filter(x=>x.approved===true).length+" of "+worker.ai_reviews.length+" reviewed":"No reviews");
    webullRow(root,"Market symbols checked",Array.isArray(worker.signals)?worker.signals.length:"Unavailable");
    const feeds=data.stream_status||worker.stream_feeds||{};
    webullRow(root,"Crypto discovery feed", "Coinbase public WebSocket · "+(feeds.crypto?.status||"NOT_CONNECTED"));
    webullRow(root,"Stock discovery feed", "Alpaca IEX WebSocket · "+(feeds.stocks?.status||"NOT_CONFIGURED")+
      (feeds.stock_feed_configured?" · configured":" · configure free feed in Broker Connections"));
    webullRow(root,"Execution quote source","Webull broker only · independent fresh bid/ask required");
    const liveSpreads=Array.isArray(feeds.crypto_spreads)?feeds.crypto_spreads:[];
    liveSpreads.forEach(x=>{
      if(typeof x.symbol!=="string"||!Number.isFinite(x.spread_pct))return;
      webullRow(root,"Coinbase "+x.symbol+" indicative spread",
        x.spread_pct.toFixed(4)+"% · "+(x.quote_age_seconds??"?")+"s old · "+
        (x.fresh?"fresh":"older observation")+
        " · NOT the Webull executable spread");
    });
    const signalSources=Array.isArray(worker.signals)?worker.signals:[];
    const sourceNames=[...new Set(signalSources.map(s=>s.source).filter(Boolean))];
    if(sourceNames.length)webullRow(root,"Scan observation source",sourceNames.join(" · "));
    const probe=worker.stock_api_probe||{};
    webullRow(root,"Webull OpenAPI stock check",probe.state||"NOT_CHECKED");
    for(const [label,name] of [["snapshot","AAPL stock snapshot"],
       ["best_bid_ask","AAPL Level 1 bid / ask"],
       ["minute_bars","AAPL 1-minute bars"]]){
      const check=probe.endpoints?.[label];
      if(check)webullRow(root,name,check.status||"UNAVAILABLE");
    }
    if(probe.checked_at)webullRow(root,"Stock API last checked",webullReadableDate(probe.checked_at));
    const ready=worker.market_readiness||{};
    for(const [asset,label] of [["stocks","Stocks"],["crypto","Crypto"]]){
      const item=ready[asset];
      if(!item)continue;
      webullRow(root,label+" market-data readiness",
        (item.status||"UNVERIFIED")+" · "+(item.detail||"No diagnostic")+
        " · "+(item.checked??0)+" quotes checked");
    }
    const eligibility=Array.isArray(worker.account_readiness)?worker.account_readiness:[];
    if(!eligibility.length){
      webullRow(root,"Webull account order eligibility","Not yet independently verified");
    }
    eligibility.forEach(a=>{
      const type=typeof a.account_type==="string"?a.account_type:"unknown";
      const suffix=typeof a.account_id==="string"?a.account_id.slice(-6):"unknown";
      webullRow(root,"Broker account "+suffix+" · "+type,
        (a.status||"UNVERIFIED")+" · "+(a.reason||"No verified account classification")+
        " · Stock cash eligible: "+(a.stocks_cash_eligible===true?"yes":"no")+
        " · Crypto cash eligible: "+(a.crypto_cash_eligible===true?"yes":"no"));
    });
    webullRow(root,"Webull orders unresolved",Array.isArray(worker.pending_orders)?worker.pending_orders.length:"Unavailable");
    webullRow(root,"Trading permission",data.execution_validated===true&&policy.enabled===true?
      "Operator armed · broker risk and order checks required":
      "DISARMED · broker order lifecycle validation required");
    webullRow(root,"Last block",worker.execution_reason||"None recorded");
    const broker=Array.isArray(worker.account_summaries)?worker.account_summaries:[];
    broker.forEach(row=>webullRow(root,
      "Account "+String(row.account_id||"").slice(-6)+" value",
      webullPrice(row.account_value)||row.status||"Unavailable"));
  }
  return data;
}
function webullPolicyFromInputs(enabled){
  return {enabled,stock_account:$("webull-stock-account")?.value||"",
    crypto_account:$("webull-crypto-account")?.value||"",
    trade_stocks:$("webull-live-stocks")?.checked===true,
    trade_crypto:$("webull-live-crypto")?.checked===true};
}
async function loadWebullMarginPreference(){
  const state=$("profile-webull-margin-status");
  const checkbox=$("profile-webull-margin-enabled");
  if(!state||!checkbox)return;
  state.textContent="Checking saved Webull account eligibility…";
  try{
    const result=await request("/api/profile/webull-margin");
    checkbox.checked=result.allow_margin_accounts===true;
    state.textContent=checkbox.checked?
      "Webull individual margin accounts eligible for cash-funded stocks only · live orders remain locked":
      "Margin-classified accounts excluded (default)";
  }catch(error){
    checkbox.checked=false;
    state.textContent="Webull margin setting unavailable: "+error.message;
  }
}
async function saveWebullMarginPreference(event){
  event.preventDefault();
  const checkbox=$("profile-webull-margin-enabled");
  const state=$("profile-webull-margin-status");
  const button=$("profile-webull-margin-save");
  if(!checkbox||!state||!button)return;
  const enabled=checkbox.checked===true;
  if(enabled&&!window.confirm("Allow individual Webull margin-classified accounts for CASH-FUNDED US stock eligibility only? Margin borrowing, leverage, shorting and live order execution remain disabled by this setting.")){
    await loadWebullMarginPreference();
    return;
  }
  button.disabled=true;
  try{
    const result=await request("/api/profile/webull-margin",{
      method:"POST",body:JSON.stringify({allow_margin_accounts:enabled})});
    state.textContent=result.allow_margin_accounts?
      "Saved · margin-classified US stock accounts eligible for cash-only consideration · live trading locked":
      "Saved · margin-classified accounts excluded and Webull live permission disarmed";
  }catch(error){
    state.textContent="Could not save Webull margin preference: "+error.message;
    await loadWebullMarginPreference();
  }finally{
    button.disabled=false;
  }
}
async function loadWebullPolicy(){
  const [data,accountData]=await Promise.all([request("/api/webull/trader"),request("/api/webull/status")]);
  const policy=data.policy||{};
  webullTraderPolicy=policy;
  webullExecutionValidated=data.execution_validated===true;
  const entries=Array.isArray(accountData.accounts)?accountData.accounts:[];
  const checked=Array.isArray(data.worker?.account_readiness)?data.worker.account_readiness:[];
  for(const [field,eligibilityFlag] of [
       ["webull-stock-account","stocks_cash_eligible"],
       ["webull-crypto-account","crypto_cash_eligible"]]){
    const select=$(field);if(!select)continue;
    select.replaceChildren();
    select.add(new Option("Choose eligible Webull account",""));
    entries.forEach(a=>{
      if(typeof a.account_id!=="string"||!a.account_id)return;
      const readiness=checked.find(x=>x.account_id===a.account_id);
      const eligible=readiness?.[eligibilityFlag]===true;
      const opt=new Option((a.account_type||"Webull")+" · "+a.account_id+
        (eligible?"":" · restricted / not verified"),a.account_id);
      opt.disabled=!eligible;
      select.add(opt);
    });
  }
  $("webull-stock-account").value=policy.stock_account||"";
  $("webull-crypto-account").value=policy.crypto_account||"";
  $("webull-live-stocks").checked=policy.trade_stocks===true;
  $("webull-live-crypto").checked=policy.trade_crypto===true;
  const restricted=checked.filter(a=>a.status==="MARGIN_ACCOUNT_BLOCKED");
  const accountNote=checked.length&&!checked.some(a=>
     a.stocks_cash_eligible===true||a.crypto_cash_eligible===true)?
     " · No cash-only eligible account verified"+
       (restricted.length?" (margin-classified account blocked)":""):
     "";
  $("webull-live-policy-state").textContent=policy.enabled===true?
    "Webull policy ARMED · the worker can place orders only after independent checks":
    "Webull policy DISARMED · scanning only; no live orders"+accountNote;
  $("webull-live-feedback").textContent=!data.execution_validated?
    "Live orders locked until Webull sandbox order and reconciliation validation completes":
    data.risk?.saved?"Webull risk plan saved · stock and crypto permissions are separate":
    "Save Webull risk plan before arming";
  $("webull-live-start").disabled=policy.enabled===true||!data.risk?.saved||!data.execution_validated;
  $("webull-live-pause").disabled=policy.enabled!==true;
}
async function webullChangePermission(enable){
  const feedback=$("webull-live-feedback");
  const policy=webullPolicyFromInputs(enable);
  if(enable){
    if(!policy.trade_stocks&&!policy.trade_crypto){
      feedback.textContent="Select at least one market and account";return;
    }
    if((policy.trade_stocks&&!policy.stock_account)||
       (policy.trade_crypto&&!policy.crypto_account)){
      feedback.textContent="Select a Webull account for each enabled market";return;
    }
    const yes=window.confirm(
      "Start AUTONOMOUS LIVE Webull trading with REAL MONEY in selected account(s)? "+
      "Cash-only stock and crypto limit orders may execute automatically. "+
      "The separate risk plan and broker checks will apply. Continue?");
    if(!yes)return;
  }
  const button=enable?$("webull-live-start"):$("webull-live-pause");
  if(button)button.disabled=true;
  feedback.textContent="Saving Webull execution permission…";
  try{
    await request("/api/webull/trader",{method:"POST",body:JSON.stringify({
      policy,confirmation:enable?"ENABLE_WEBULL_LIVE":""})});
    await loadWebullPolicy();
    await loadWebullTrader();
    feedback.textContent=enable?
      "Webull live policy armed. Worker must independently pass all risk and broker checks.":
      "Webull live execution paused. Pending broker orders still require reconciliation.";
  }catch(error){feedback.textContent="Webull authorization blocked: "+error.message;}
  finally{
    if(button){
      if(enable){button.disabled=webullTraderPolicy?.enabled===true||!webullExecutionValidated;}
      else{button.disabled=webullTraderPolicy?.enabled!==true;}
    }
  }
}
async function loadWebullEvidence(){
  const data=await request("/api/webull/evidence");
  const root=webullListRoot("webull-evidence-list"),items=Array.isArray(data.items)?data.items:[];
  if($("webull-evidence-updated"))$("webull-evidence-updated").textContent=
    items.length?items.length+" recent Webull scans, newest first":"No completed Webull scans recorded";
  if(!root)return;
  if(!items.length){webullRow(root,"Status","Awaiting first Webull scan");return;}
  items.slice(0,25).forEach(item=>{
    webullRow(root,"Scan · "+webullReadableDate(item.updated_at),
      (item.execution_status||"NO_EXECUTION")+
      " · "+(item.execution_reason||"No broker order"));
    const signals=Array.isArray(item.signals)?item.signals:[];
    signals.slice(0,6).forEach(s=>webullRow(root,
      (s.asset==="CRYPTO"?"Crypto ":"Stock ")+(s.symbol||"?"),
      (s.technical_approved?"MOMENTUM CANDIDATE":"No qualified signal")+
      " · "+(s.source||"Source unavailable")+
      " · "+(s.reason||"No recorded reason")+
      (s.momentum_pct==null?"":" · "+s.momentum_pct+"% momentum")));
    const ai=Array.isArray(item.ai_reviews)?item.ai_reviews:[];
    ai.slice(0,3).forEach(a=>webullRow(root,
      "AI "+(a.approved?"PASS":"BLOCK")+" · "+(a.symbol||"?"),
      (a.model||"Model unavailable")+" · "+(a.reason||"No rationale available")));
  });
}
async function loadWebullOrders(){
  const data=await request("/api/webull/trader");
  const root=webullListRoot("webull-orders-list");
  const rows=Array.isArray(data.orders)?data.orders:[];
  if($("webull-orders-updated"))$("webull-orders-updated").textContent=
    "Webull-specific local intents: "+rows.length+
    " · live permission "+(data.policy?.enabled?"ARMED":"DISARMED");
  if(!root)return;
  if(!rows.length){webullRow(root,"No Webull bot orders",
    "No automated orders submitted by this Webull worker");return;}
  rows.forEach(order=>{
    webullRow(root,(order.symbol||"Unknown")+" · "+(order.side||""),
      (order.status||"UNKNOWN")+" · account "+String(order.account||"").slice(-6)+
      " · qty "+(order.quantity||"?")+" · limit "+(webullPrice(order.limit_price)||"unavailable"));
    webullRow(root,"Broker fill evidence · "+String(order.client_id||"").slice(0,8),
      order.status==="FILLED"?
      "Filled "+order.filled_qty+" @ "+(webullPrice(order.filled_price)||"?")+
      " · "+webullReadableDate(order.fill_at):
      "Not broker-confirmed filled · checked "+webullReadableDate(order.checked_at));
  });
}
function webullDashboardReset(reason){
  for(const id of ["webull-equity","webull-cash","webull-holdings-count","webull-orders-count",
    "webull-performance-value","webull-performance-pnl","webull-performance-return"])
    if($(id))$(id).textContent="Unavailable";
  if($("webull-performance-coverage"))$("webull-performance-coverage").textContent="No verified account data";
  if($("webull-performance-note"))$("webull-performance-note").textContent=reason;
}
function webullNumeric(raw){
  if(typeof raw!=="string"&&typeof raw!=="number")return null;
  const s=String(raw);
  if(!/^-?(?:0|[1-9]\d*)(?:\.\d{1,8})?(?:[Ee][+-]?\d{1,3})?$/.test(s))return null;
  const n=Number(s);return Number.isFinite(n)&&Math.abs(n)<1e13?n:null;
}
function renderWebullPortfolio(result){
  const b=result.balances||{},holdings=Array.isArray(result.positions)?result.positions:[];
  const usd=b.total_asset_currency==="USD";
  const equity=usd?webullPrice(b.total_net_liquidation_value):null;
  const cash=usd?webullPrice(b.total_cash_balance):null;
  const value=usd?webullPrice(b.total_market_value):null;
  const pnl=usd?webullPrice(b.total_unrealized_profit_loss):null;
  $("webull-equity").textContent=equity||"Unavailable";
  $("webull-cash").textContent=cash||"Unavailable";
  $("webull-holdings-count").textContent=String(holdings.length);
  $("webull-performance-value").textContent=value||"Unavailable";
  $("webull-performance-pnl").textContent=pnl||"Unavailable";
  const market=usd?webullNumeric(b.total_market_value):null;
  const gain=usd?webullNumeric(b.total_unrealized_profit_loss):null;
  const basis=market!==null&&gain!==null?market-gain:null;
  $("webull-performance-return").textContent=basis!==null&&basis>0?
    ((gain/basis)*100).toFixed(2)+"%":"Unavailable";
  $("webull-performance-coverage").textContent=usd?"Broker-reported USD account":"Currency unverified";
  $("webull-performance-note").textContent=pnl?
    "Unrealized P/L uses Webull account figures; not realized profit or tax cost basis.":
    "Broker did not supply a verified USD unrealized P/L. No estimate is inferred.";
  const root=$("webull-positions");root.replaceChildren();
  if(!holdings.length){root.textContent="No holdings reported by this account.";return;}
  const table=document.createElement("table"),head=document.createElement("thead"),body=document.createElement("tbody");
  const tr=document.createElement("tr");
  ["Symbol","Asset","Quantity","Last price","Unrealized P/L"].forEach(v=>{
    const th=document.createElement("th");th.textContent=v;tr.appendChild(th);});
  head.appendChild(tr);table.appendChild(head);
  holdings.forEach(h=>{
    const row=document.createElement("tr");
    [h.symbol||"Unknown",h.instrument_type||"Asset",h.quantity??"Unavailable",
      webullPrice(h.last_price)||"Unavailable",webullPrice(h.unrealized_profit_loss)||"Unavailable"]
      .forEach(v=>{const td=document.createElement("td");td.textContent=String(v);row.appendChild(td);});
    body.appendChild(row);
  });
  table.appendChild(body);root.appendChild(table);
}
async function loadWebullWorkspace(){
  const health=$("webull-connectivity"),accounts=$("webull-account");
  const updated=$("webull-updated"),balances=$("webull-balance-fields");
  const positions=$("webull-positions");
  if(!health||!accounts)return;
  health.textContent="Checking Webull account access…";
  const data=await request("/api/webull/status");
  updateWebullTile(data);
  accounts.replaceChildren();
  const entries=Array.isArray(data.accounts)?data.accounts:[];
  if(!data.connected||!entries.length){
    health.textContent=data.credentials_saved?"Connection not verified: "+(data.reason||"Check Webull permissions"):"Webull credentials required";
    accounts.add(new Option("No authenticated accounts available",""));
    balances.replaceChildren();
    positions.textContent="No authenticated position snapshot.";
    webullDashboardReset("Connect a verified Webull account to load performance.");
    updated.textContent="Open Broker Connections to save Webull API credentials.";
    return;
  }
  health.textContent="Authenticated Webull "+data.environment+" account access verified";
  for(const entry of entries){
    accounts.add(new Option((entry.account_type||"Webull account")+" · "+entry.account_id,entry.account_id));
  }
  await loadWebullAccount();
  loadWebullTrader().catch(()=>{if($("webull-worker-updated"))$("webull-worker-updated").textContent="Worker status unavailable";});
}
function webullReadOnlyRows(root,label,data){
  const wrapper=document.createElement("div");
  const heading=document.createElement("strong");
  heading.textContent=label;wrapper.appendChild(heading);
  const content=document.createElement("pre");
  content.style.cssText="white-space:pre-wrap;overflow-wrap:anywhere;max-height:320px;overflow:auto;font-size:12px";
  content.textContent=JSON.stringify(data,null,2);
  wrapper.appendChild(content);
  root.appendChild(wrapper);
}
async function loadWebullAccount(){
  const id=$("webull-account")?.value;
  const updated=$("webull-updated"),balances=$("webull-balance-fields");
  const positions=$("webull-positions");
  if(!id||!balances||!positions)return;
  balances.replaceChildren();positions.replaceChildren();
  updated.textContent="Checking selected Webull balance and holdings…";
  try{
    const result=await request("/api/webull/portfolio?account_id="+encodeURIComponent(id));
    const moneyFields=result.balances||{};
    renderWebullPortfolio(result);
    balances.replaceChildren();
    webullRow(balances,"Account value (USD)",webullPrice(moneyFields.total_net_liquidation_value));
    webullRow(balances,"Cash balance (USD)",webullPrice(moneyFields.total_cash_balance));
    webullRow(balances,"Holdings value (USD)",webullPrice(moneyFields.total_market_value));
    webullRow(balances,"Unrealized P/L",webullPrice(moneyFields.total_unrealized_profit_loss));
    const assets=Array.isArray(moneyFields.account_currency_assets)?moneyFields.account_currency_assets:[];
    assets.filter(x=>x.currency==="USD").forEach(a=>
      webullRow(balances,"Available USD buying power",webullPrice(a.buying_power)));
    // renderWebullPortfolio() already populated the holdings table.
    // Do not clear it after rendering.
    updated.textContent="Broker data refreshed "+new Date().toLocaleString()+" · "+result.environment+
      " · read-only, not an execution authorization";
  }catch(error){
    updated.textContent="Unable to verify account data: "+error.message;
    positions.textContent="Current positions unavailable; no values inferred.";
    webullDashboardReset("Broker account request failed; performance is unavailable.");
  }
}
async function loadWebullRisk(){
  const plan=await request("/api/webull/risk");
  $("webull-risk-position").value=plan.max_position_pct;
  $("webull-risk-order").value=plan.max_order_usd;
  $("webull-risk-loss").value=plan.max_daily_loss_usd;
  $("webull-risk-positions").value=plan.max_open_positions;
  $("webull-risk-status").textContent=plan.saved?"Risk limits saved":"Defaults · save before live trading";
  await loadWebullPolicy();
}
async function saveWebullRisk(e){
  e.preventDefault();
  const form=$("webull-risk-form");if(!form.reportValidity())return;
  const payload={max_position_pct:Number($("webull-risk-position").value),
    max_order_usd:Number($("webull-risk-order").value),
    max_daily_loss_usd:Number($("webull-risk-loss").value),
    max_open_positions:Number($("webull-risk-positions").value)};
  try{
    const result=await request("/api/webull/risk",{method:"POST",body:JSON.stringify(payload)});
    $("webull-risk-status").textContent=result.saved?"Webull risk limits saved":"Not saved";
    await loadWebullPolicy();
  }catch(error){$("webull-risk-status").textContent="Unable to save: "+error.message;}
}
document.addEventListener("DOMContentLoaded",()=>{
  $("webull-refresh")?.addEventListener("click",()=>loadWebullWorkspace().catch(err=>toast(err.message,true)));
  $("webull-account")?.addEventListener("change",()=>loadWebullAccount().catch(err=>toast(err.message,true)));
  $("webull-risk-form")?.addEventListener("submit",saveWebullRisk);
  $("webull-live-start")?.addEventListener("click",()=>webullChangePermission(true));
  $("webull-live-pause")?.addEventListener("click",()=>webullChangePermission(false));
  $("webull-evidence-refresh")?.addEventListener("click",()=>loadWebullEvidence().catch(err=>toast(err.message,true)));
  $("webull-orders-refresh")?.addEventListener("click",()=>loadWebullOrders().catch(err=>toast(err.message,true)));
  setInterval(()=>{
    if(!csrf)return;
    if(activeView==="webull")loadWebullTrader().catch(()=>{});
    if(activeView==="webull-decisions")loadWebullEvidence().catch(()=>{});
    if(activeView==="webull-orders")loadWebullOrders().catch(()=>{});
  },30000);
});
function showView(view) {
  if(!["workspaces","live","decisions","live-risk","local","forecast","overview","trades","reviews","settings","profile","brokers","robinhood","robinhood-risk","robinhood-decisions","robinhood-forecast","operations","webull","webull-risk","webull-decisions","webull-orders"].includes(view))return;
  activeView=view;
  // Shared AI and operations views must not inherit Schwab or Robinhood context.
  const liveViews=["live","decisions","live-risk","forecast"];
  const paperViews=["overview","trades","reviews","settings"];
  if(liveViews.includes(view))selectWorkspace("live");
  if(paperViews.includes(view))selectWorkspace("paper");
  const rhViews=["robinhood","robinhood-risk","robinhood-decisions","robinhood-forecast"];
  if(rhViews.includes(view))selectWorkspace("robinhood_crypto");
  const webullViews=["webull","webull-risk","webull-decisions","webull-orders"];
  if(webullViews.includes(view))selectWorkspace("webull");
  const context=liveViews.includes(view)?"live":paperViews.includes(view)?"paper":rhViews.includes(view)?"robinhood_crypto":webullViews.includes(view)?"webull":null;
  $("sidebar-account-context").classList.toggle("hidden",context===null);
  if(context)$("sidebar-current-account").textContent=context==="live"?"Schwab live":context==="paper"?"Paper Trading":context==="webull"?"Webull":"Robinhood Crypto";
  $("live-nav-group").classList.toggle("hidden",context!=="live");
  $("paper-nav-group").classList.toggle("hidden",context!=="paper");
  $("robinhood-nav-group")?.classList.toggle("hidden",context!=="robinhood_crypto");
  $("webull-nav-group")?.classList.toggle("hidden",context!=="webull");
  // The overview sidebar owns shared tools; keep them visible while either tool is open.
  $("overview-shared-nav")?.classList.toggle("hidden",!["workspaces","local","operations"].includes(view));
  document.querySelectorAll(".view").forEach(v=>v.classList.toggle("hidden",v.id!=="view-"+view));
  document.querySelectorAll(".nav-item").forEach(b=>b.classList.toggle("active",b.dataset.view===view));
  const titles={workspaces:"All accounts",live:"Schwab live",decisions:"Live AI evidence",
     "live-risk":"Live risk settings",local:"AI workstation models",forecast:"Next session forecast",
    overview:"Paper simulator",trades:"Paper history",reviews:"Paper AI audit",
settings:"Paper risk settings",profile:"User profile",brokers:"Broker connections",operations:"Trading operations",robinhood:"Robinhood Crypto","robinhood-risk":"Robinhood risk settings",
    "robinhood-decisions":"Robinhood AI evidence",
    "robinhood-forecast":"Crypto scan forecast",webull:"Webull","webull-risk":"Webull risk plan",
    "webull-decisions":"Webull AI evidence","webull-orders":"Webull orders"};
  $("breadcrumb-divider").classList.toggle("hidden",view==="workspaces");
  $("breadcrumb").textContent=titles[view];
  $("live-mode-banner").classList.toggle("hidden",!liveViews.includes(view));
  if(view==="trades" || view==="reviews") loadPage(view,page[view]).catch(err=>toast(err.message,true));
  if(view==="settings"){
    if(status) populateSettings(status.control.settings);
    loadPaperService().catch(err=>toast(err.message,true));
  }
  if(view==="profile")loadWebullMarginPreference().catch(err=>toast(err.message,true));
  if(view==="local") loadLocalModels().catch(err=>toast(err.message,true));
  if(view==="forecast") loadForecast().catch(err=>toast(err.message,true));
  if(view==="operations") loadOperations().catch(err=>{if($("ops-updated"))$("ops-updated").textContent="Unable to load operations: "+err.message;});
  if(view==="brokers") loadBrokerWorkspace().catch(err=>toast(err.message,true));
  if(view==="webull")loadWebullWorkspace().catch(err=>toast(err.message,true));
  if(view==="webull-risk")loadWebullRisk().catch(err=>toast(err.message,true));
  if(view==="webull-decisions")loadWebullEvidence().catch(err=>toast(err.message,true));
  if(view==="webull-orders")loadWebullOrders().catch(err=>toast(err.message,true));
  if(view==="robinhood") loadRobinhoodWorkspace().catch(err=>toast(err.message,true));
  if(view==="robinhood-risk") loadRobinhoodRisk().catch(err=>toast(err.message,true));
  if(view==="robinhood-decisions") loadRobinhoodDecisionEvidence().catch(err=>toast(err.message,true));
  if(view==="robinhood-forecast") loadRobinhoodExtras().catch(err=>toast(err.message,true));
  if(view==="workspaces") refreshRobinhoodTile().catch(()=>{});
  if(view==="workspaces") refreshWebullTile().catch(()=>{});
  if(view==="live-risk"&&lastLive) populateLiveRisk(lastLive);
  if(view==="profile") request("/api/profile").then(p=>{
    $("profile-version").textContent="Installed v"+p.version;
  }).catch(err=>toast(err.message,true));
}
async function refreshAll(){
  if(refreshing)return;
  refreshing=true;
  try{
    const [response,performance,trades,live] = await Promise.all([
      request("/api/status"),request("/api/performance"),
      request("/api/trades?page=1&limit=5"),request("/api/live")
    ]);
    status=response;
    updateWorkspaceBalances(response,live);
    updateAccountActivity(response,live);

    renderOverview(response,performance.points||[],trades.items||[]);
    renderLiveView(live);
    if(activeView==="live-risk"&&document.activeElement&&!document.activeElement.closest("form"))
      populateLiveRisk(live);
    $("trade-count-nav").textContent=intNum(response.account.trade_count);
    if(activeView==="trades" || activeView==="reviews"){
      await loadPage(activeView,page[activeView]);
    }
    if(activeView==="settings" && !document.activeElement.closest("form")) {
      populateSettings(response.control.settings);
    }
  }finally{refreshing=false;}
}
function renderOverview(data,points,recent){
  const {account:a,control:c,runtime:r}=data;
  const active=r.online;
  const mode=c.mode || "stopped";
  $("mode-pill").textContent=mode[0].toUpperCase()+mode.slice(1);
  $("mode-pill").className="mode-tag "+mode;
  $("start-btn").disabled=(mode==="running");
  $("pause-btn").disabled=(mode==="paused");
  $("stop-btn").disabled=(mode==="stopped");
  $("stat-equity").textContent=money(a.equity);
  $("stat-equity-desc").textContent=a.initialized?"Mark-to-market paper equity":"Starting simulated balance";
  $("stat-cash").textContent=money(a.cash);
  $("stat-cash-desc").textContent="Spendable cash, excluding reserved profits";
  $("stat-pnl").textContent=money(a.realized_pnl);
  $("stat-pnl").classList.toggle("green",a.realized_pnl>0);
  $("stat-pnl").classList.toggle("red",a.realized_pnl<0);
  $("stat-unrealized").textContent=`Unrealized ${money(a.unrealized_pnl)}`;
  $("stat-trades").textContent=intNum(a.trade_count);
  $("stat-reviews").textContent=`${intNum(a.review_count)} AI evaluations recorded`;
  $("chart-value").innerHTML=`${esc(money(a.equity))} <small>Current equity</small>`;
  renderChart(points,a.equity);
  const s=c.settings;
  $("alloc-available").textContent=money(a.cash);
  $("alloc-pct").textContent=pct(s.allocation_pct);
  $("alloc-bar").style.width=Math.max(0,Math.min(100,s.allocation_pct))+"%";
  $("alloc-budget").textContent=money(orderBudget(a,s));
  $("alloc-reserve").textContent=money(a.reserved_profit);
  $("alloc-loss").textContent=money(s.max_daily_loss);
  $("alloc-reinvest").textContent=pct(s.reinvest_pct);
  $("recent-trades").innerHTML=recent.length?recent.map(t=>
    `<tr><td><span class="symbol">${esc(t.symbol)}</span></td>
    <td><span class="pill ${t.action==="PAPER_BUY"?"buy":"sell"}">${esc(t.action==="PAPER_BUY"?"BUY":"SELL")}</span></td>
    <td>${money((t.quantity||0)*(t.price||0))}</td>
    <td class="muted-cell">${esc(t.reason||"Legacy trade — no reason recorded")}</td></tr>`).join("")
    :'<tr><td colspan="4" class="empty-row">No paper trades yet. Candidate decisions will appear after price data and AI are connected.</td></tr>';
  $("positions-list").innerHTML=a.positions.length?a.positions.map(p=>
    `<div class="position"><div><strong>${esc(p.symbol)}</strong><small>${esc(p.quantity)} units · entry ${money(p.entry_price)}</small></div>
    <div class="position-right"><strong>${money(p.market_value)}</strong><small class="${p.unrealized_pnl>=0?"green":"red"}">${money(p.unrealized_pnl)} P&L</small></div></div>`).join("")
    :'<p class="muted" style="font-size:12px;margin:28px 0">No open simulated positions.</p>';
  const warning=$("data-warning");
  let message;
  if(!r.online)message=["Monitor not reporting","The Docker trading worker may be stopped or unable to write its heartbeat."];
  else if(!r.ai_model_configured)message=["Paper AI reviewer not configured",
    "Market observations can be collected, but simulated buys remain blocked until a compatible model is configured."];
  else if(r.market_source==="schwab_read_only" && !r.last_error)
    message=["Shared brokerage market data available",
      "Paper decisions use the same market scanner and AI approval as Schwab; fills remain entirely simulated."];
  else if(r.market_source==="schwab_read_only")
    message=["Paper market data temporarily unavailable",
      "Shared scanner could not obtain a usable read-only brokerage quote. No simulated order was placed."];
  else if(r.public_market_feed && r.paper_quotes_available>0)
    message=["Paper price feed reporting",
      r.paper_quotes_available+" public timestamped observations received. Simulated entries still require strategy and AI approval."];
  else if(r.public_market_feed)
    message=["Paper price feed waiting",
      "No recent public quotes are available. Markets may be closed, data delayed, or the provider unreachable."];
  else message=["No paper market feed configured",
    "The strategy requires timestamped public market prices; paper trades are not broker orders."];
  if(r.last_paper_decision==="AI_VETO"){
    message=["Paper entry rejected by AI", (r.last_paper_symbol||"Candidate")+
      ": "+(r.last_paper_reason||"AI review did not approve this entry")];
  } else if(r.last_paper_decision==="NO_SIGNAL"){
    message=["No qualified paper entry", "Strategy scan found no qualifying completed-bar crossover. "+
      "No order was simulated."];
  } else if(r.last_paper_decision==="INSUFFICIENT_CASH"){
    message=["Paper order budget insufficient", "A candidate was found but its affordable whole-share quantity was zero."];
  }
  warning.querySelector("strong").textContent=message[0];
  warning.querySelector("p").textContent=message[1];
  if(activeView==="settings" && document.activeElement && !document.activeElement.closest("form"))populateSettings(s);
}
function orderBudget(account,s) {
  let result=Math.min((account.cash||0)*(s.allocation_pct||0)/100,(account.equity||0)*(s.max_position_pct||0)/100);
  if(s.max_order_usd>0) result=Math.min(result,s.max_order_usd);
  return Math.max(0,result);
}
function renderChart(points,currentEquity) {
  let series=points.filter(p=>Number.isFinite(Number(p.equity))).slice(-100).map(p=>Number(p.equity));
  if(!series.length){$("equity-chart").innerHTML='<div class="chart-empty">Equity history will appear after the monitor records snapshots.</div>';return;}
  if(series.length===1)series=[series[0],series[0]];
  const low=Math.min(...series),high=Math.max(...series),range=Math.max(1,high-low);
  const w=850,h=180,pad=12;
  const coords=series.map((v,i)=>[pad+(i/(series.length-1))*(w-pad*2),pad+(1-(v-low)/range)*(h-pad*2)]);
  const line=coords.map(([x,y])=>`${x.toFixed(2)},${y.toFixed(2)}`).join(" ");
  const fill=`${pad},${h} ${line} ${w-pad},${h}`;
  $("equity-chart").innerHTML=
    `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" role="img" aria-label="Historical simulated portfolio value">
      <defs><linearGradient id="fade" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#4f9df4" stop-opacity=".27"/><stop offset="100%" stop-color="#4f9df4" stop-opacity="0"/></linearGradient></defs>
      <line x1="0" y1="45" x2="${w}" y2="45" stroke="#2a3850" stroke-dasharray="4 6"/>
      <line x1="0" y1="90" x2="${w}" y2="90" stroke="#2a3850" stroke-dasharray="4 6"/>
      <line x1="0" y1="135" x2="${w}" y2="135" stroke="#2a3850" stroke-dasharray="4 6"/>
      <polygon points="${fill}" fill="url(#fade)"/><polyline points="${line}" fill="none" stroke="#63b3ff" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>`;
}
async function setMode(mode){
  if(!status)return;
  const question=mode==="stopped"?"Stop the trading strategy? The dashboard and Docker service will remain online.":mode==="paused"?"Pause processing new quotes?":"Start processing paper-trading quotes? No live orders will be placed.";
  if(!window.confirm(question))return;
  const el=document.querySelector(`[data-mode="${mode}"]`);el.disabled=true;
  try{
    const data=await request("/api/mode",{method:"POST",body:JSON.stringify({revision:status.control.revision,mode})});
    status.control=data.control;
    toast(`Strategy mode changed to ${mode}. It will take effect on the next bot cycle.`);
    await refreshAll();
  }catch(err){toast(err.message,true);}
  finally{el.disabled=false;}
}
function populateSettings(s) {
  if(!s)return;
  for(const key of ["allocation_pct","max_order_usd","max_position_pct","max_daily_loss","max_open_positions","reinvest_pct","daily_growth_target_pct"]){
    $(key).value=s[key];
  }
  updatePreview();
}
function formSettings() {
  return {
    allocation_pct:Number($("allocation_pct").value),
    max_order_usd:Number($("max_order_usd").value),
    max_position_pct:Number($("max_position_pct").value),
    max_daily_loss:Number($("max_daily_loss").value),
    max_open_positions:Number($("max_open_positions").value),
    reinvest_pct:Number($("reinvest_pct").value),
    daily_growth_target_pct:Number($("daily_growth_target_pct").value),
  };
}
function updatePreview(){
  if(!status)return;
  const a=status.account,s=formSettings();
  $("preview-order").textContent=money(orderBudget(a,s));
  $("preview-cash").textContent=money(a.cash);
  $("preview-loss").textContent=money(s.max_daily_loss);
  $("preview-reinvest").textContent=pct(s.reinvest_pct);
  $("preview-growth").textContent=pct(s.daily_growth_target_pct);
}
let paperServiceEnabled=null;
function paperServiceUI(enabled,message){
  paperServiceEnabled=enabled;
  $("paper-service-toggle").textContent=enabled===null?"Check status":
    enabled?"Stop paper simulator":"Start paper simulator";
  $("paper-service-status").textContent=message ||
    (enabled===null?"Status unavailable":
     enabled?"Background paper simulator is enabled":"Background paper simulator is disabled");
}
async function loadPaperService(){
  const d=await request("/api/integrations");
  paperServiceUI(d.paper_enabled===true);
}
async function togglePaperService(){
  const button=$("paper-service-toggle");
  button.disabled=true;
  try{
    if(paperServiceEnabled===null){
      await loadPaperService();return;
    }
    const next=!paperServiceEnabled;
    if(!window.confirm(next?
      "Start the automated paper trading simulator using VIRTUAL FUNDS only?":
      "Stop the automated paper simulator? Past paper trades and positions remain recorded."))return;
    const result=await request("/api/integrations",{
      method:"POST",body:JSON.stringify({paper_enabled:next})});
    paperServiceUI(result.paper_enabled===true,
      next?"Paper simulator enabled. The worker starts on its next runtime cycle.":
           "Paper simulator disabled. Prior paper records are preserved.");
  }catch(error){paperServiceUI(paperServiceEnabled,error.message);}
  finally{button.disabled=false;}
}
async function saveSettings(ev){
  ev.preventDefault();
  if(!status)return;
  const form=$("settings-form");
  if(!form.reportValidity())return;
  const settings=formSettings();
  if(!Number.isInteger(settings.max_open_positions))return toast("Open positions must be an integer.",true);
  const previous=status.control.settings;
  if(settings.max_position_pct>previous.max_position_pct || settings.max_daily_loss>previous.max_daily_loss){
    if(!window.confirm("You are increasing the permitted paper-trading risk. Continue?"))return;
  }
  $("settings-save").disabled=true;
  try{
    const data=await request("/api/settings",{method:"POST",body:JSON.stringify({revision:status.control.revision,settings})});
    status.control=data.control;
    $("setting-msg").textContent="Saved. Bot applies settings on its next cycle.";
    toast("Risk and capital settings saved.");
    await refreshAll();
  }catch(err){toast(err.message,true);$("setting-msg").textContent=err.message;}
  finally{$("settings-save").disabled=false;}
}
async function loadPage(kind,targetPage){
  const payload=await request(`/api/${kind}?page=${targetPage}&limit=25`);
  page[kind]=payload.page;
  pageData[kind]=payload;
  $(kind+"-total").textContent=`${intNum(payload.total)} records`;
  $(kind+"-page").textContent=`Page ${payload.page} of ${Math.max(1,Math.ceil(payload.total/payload.limit))}`;
  $(kind+"-prev").disabled=payload.page<=1;
  $(kind+"-next").disabled=payload.page*payload.limit>=payload.total;
  if(kind==="trades") {
    $("trades-table").innerHTML=payload.items.length?payload.items.map((t,i)=>{
      const pnl=Number(t.realized_pnl||0);
      const reason=t.reason||"No rationale recorded (legacy trade)";
      const ai=t.ai_review?`<div class="muted-cell">AI: ${esc(t.ai_review.model||"unknown")} · ${esc(t.ai_review.reason||"")}</div>`:"";
      return `<tr>
        <td>${esc(t.timestamp||"—")}</td><td class="symbol">${esc(t.symbol)}</td>
        <td><span class="pill ${t.action==="PAPER_BUY"?"buy":"sell"}">${esc(t.action)}</span></td>
        <td>${esc(t.quantity)}</td><td>${money(t.price)}</td>
        <td class="${pnl>=0?"green":"red"}">${t.action==="PAPER_SELL"?money(pnl):"—"}</td>
        <td class="reason">${esc(reason)}${ai}</td>
        <td><button class="btn secondary tiny" data-export-paper-index="${payload.total-(payload.page-1)*payload.limit-1-i}">↓ XLSX</button></td></tr>`;
    }).join(""):'<tr><td colspan="7" class="empty-row">No executed simulated trades yet.</td></tr>';
  } else {
    $("reviews-table").innerHTML=payload.items.length?payload.items.map(r=>
      `<tr><td>${esc(r.timestamp||"—")}</td><td class="symbol">${esc(r.symbol)}</td>
      <td><span class="pill ${r.approved?"approve":"reject"}">${r.approved?"APPROVED":"REJECTED"}</span></td>
      <td>${esc(r.quantity)} × ${money(r.price)}</td><td>${esc(r.model||"—")}</td>
      <td class="reason">${esc(r.reason||"—")}${r.risk_flags&&r.risk_flags.length?`<div class="muted-cell">Flags: ${esc(r.risk_flags.join(", "))}</div>`:""}</td></tr>`).join("")
      :'<tr><td colspan="6" class="empty-row">No AI evaluations recorded yet.</td></tr>';
  }
}
async function downloadWorkbook(url,filename,button){
  const original=button?.textContent;
  if(button){button.disabled=true;button.textContent="Preparing…";}
  try{
    const response=await fetch(url,{credentials:"same-origin",cache:"no-store",
      headers:{"Accept":"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}});
    if(response.status===401){csrf=null;showLogin();throw Error("Session expired. Please sign in.");}
    if(!response.ok){
      const text=await response.json().catch(()=>({}));
      throw Error(text.error||"Excel export failed (HTTP "+response.status+")");
    }
    const type=response.headers.get("Content-Type")||"";
    if(!type.includes("spreadsheetml.sheet"))throw Error("Server did not produce an Excel workbook");
    const blob=await response.blob();
    if(!blob.size||blob.size>15_000_000)throw Error("Excel workbook size invalid");
    const address=URL.createObjectURL(blob),link=document.createElement("a");
    link.href=address;link.download=filename;document.body.appendChild(link);
    link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(address),1000);
    toast("Excel workbook downloaded.");
  }catch(err){toast(err.message,true);}
  finally{if(button){button.disabled=false;button.textContent=original;}}
}
async function exportTrades(){
  await downloadWorkbook("/api/paper/export.xlsx","autotrader-paper-trades.xlsx",$("export-trades"));
}
document.addEventListener("DOMContentLoaded",()=>{
  $("robinhood-risk-form")?.addEventListener("submit",saveRobinhoodRisk);
  $("rh-evidence-refresh")?.addEventListener("click",()=>loadRobinhoodDecisionEvidence().catch(err=>toast(err.message,true)));
  $("robinhood-overview-start")?.addEventListener("click",()=>showView("robinhood-risk"));
  $("robinhood-overview-pause")?.addEventListener("click",()=>showView("robinhood-risk"));
  $("robinhood-live-start")?.addEventListener("click",()=>{
    if(!$("robinhood-risk-form").reportValidity())return;
    $("robinhood-risk-activate").checked=true;
    $("robinhood-risk-form").requestSubmit();
  });
  $("robinhood-live-stop")?.addEventListener("click",()=>{
    $("robinhood-risk-activate").checked=false;
    $("robinhood-risk-form").requestSubmit();
  });
});
document.addEventListener("DOMContentLoaded",init);


async function changeDashboardPassword(ev){
  ev.preventDefault();
  const current=$("profile-current").value;
  const next=$("profile-new").value;
  const confirmation=$("profile-confirm").value;
  const feedback=$("profile-message");
  feedback.textContent="";
  if(next!==confirmation){feedback.textContent="New passwords do not match.";return;}
  if(next.length<10 || next.length>256 || !/[A-Z]/.test(next) ||
     !/[0-9]/.test(next) || !/[^\p{L}\p{N}\s]/u.test(next) ||
     /[\x00-\x1F\x7F]/.test(next)){
    feedback.textContent="Use at least 10 characters, an uppercase letter, a number and a symbol.";return;
  }
  const button=$("profile-save");
  button.disabled=true;
  try{
    await request("/api/profile/password",{method:"POST",
      body:JSON.stringify({current_password:current,new_password:next})});
    $("profile-password-form").reset();
    csrf=null;
    showLogin();
    $("login-error").textContent="Password changed. Sign in with your new password.";
  }catch(err){feedback.textContent=err.message;}
  finally{button.disabled=false;}
}
async function checkForUpdate(){
  const status=await request("/api/update");
  const banner=$("update-banner");
  const details=$("profile-update-status");
  if(details){
    details.textContent=status.status==="checked"
      ? "Installed v"+status.installed+" · Latest v"+status.latest+
        " · Last checked "+(status.checked_at||"unknown")
      : "Unable to check GitHub releases; verify internet access. TrueNAS image updates are independent.";
  }
  if(status.update_available && typeof status.release_url==="string" &&
     status.release_url.startsWith("https://github.com/Zoncko98/Auto-Trade/tree/v")){
    banner.textContent="Update v"+status.latest+" available";
    banner.href=status.release_url;
    banner.classList.remove("hidden");
  }else{
    banner.classList.add("hidden");
    banner.removeAttribute("href");
  }
}

document.addEventListener("click",e=>{
 const tab=e.target.closest("[data-ops-section]");
 if(tab)opsSection(tab.dataset.opsSection);
 if(e.target.closest("#operations-refresh"))loadOperations().catch(err=>{if($("ops-updated"))$("ops-updated").textContent=err.message;});
});
document.addEventListener("change",e=>{if(e.target.id==="ops-decision-select")opsInspect();});

if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",initWorkspaceSorting,{once:true});
else initWorkspaceSorting();
