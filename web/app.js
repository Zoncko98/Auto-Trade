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
const AVAILABLE_WORKSPACES = Object.freeze(["live","paper","robinhood_crypto"]);
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
function clearWorkspaceBalances(){
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
function positionRobinhoodTile(configured){
  const tile=document.querySelector('[data-workspace="robinhood_crypto"]');
  const active=document.querySelector('.workspace-tile-grid');
  const upcoming=document.querySelector('.workspace-upcoming-grid');
  if(!tile||!active||!upcoming)return;
  const target=configured?active:upcoming;
  if(tile.parentElement!==target)target.appendChild(tile);
  tile.classList.toggle("workspace-tile-featured",configured);
  tile.classList.toggle("workspace-tile-compact",!configured);
  const label=tile.querySelector(".workspace-tile-equity-label");
  if(label)label.hidden=!configured;
}
function robinhoodBuyingPower(accounts){
  const values=[];
  for(const account of accounts){
    const currency=account.buying_power_currency;
    const raw=account.buying_power;
    if(currency!=="USD" || typeof raw!=="string" ||
       !/^(?:0|[1-9]\d*)(?:\.\d{1,8})?$/.test(raw))return null;
    const value=Number(raw);
    if(!Number.isFinite(value)||value>1e12)return null;
    values.push(value);
  }
  return values.length?values.reduce((a,b)=>a+b,0):null;
}
function updateRobinhoodTile(result){
  const accounts=Array.isArray(result.accounts)?result.accounts:[];
  const configured=result.credentials_saved===true||result.connected===true;
  positionRobinhoodTile(configured);
  const statusNode=$("workspace-robinhood-status");
  const amountNode=$("workspace-robinhood-balance");
  if(!statusNode||!amountNode)return;
  const verified=result.connected===true && accounts.length>0;
  statusNode.textContent=verified?
    (accounts.some(a=>a.is_api_tradable===true)?"ACCOUNT VERIFIED":"CONNECTED · RESTRICTED"):
    (configured?"CREDENTIALS SAVED · CHECK CONNECTION":"SET UP ROBINHOOD");
  const buyingPower=verified?robinhoodBuyingPower(accounts):null;
  amountNode.textContent=buyingPower===null?"Buying power unavailable":money(buyingPower);
  amountNode.title=buyingPower===null?
    "No verified USD buying power was returned by the Robinhood Crypto API":
    "Verified Robinhood Crypto USD buying power; this is not total portfolio equity";
}
async function refreshRobinhoodTile(){
  try{
    updateRobinhoodTile(await request("/api/robinhood/status"));
  }catch(_){
    const statusNode=$("workspace-robinhood-status");
    if(statusNode)statusNode.textContent="CONNECTION CHECK FAILED";
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
}
function robinhoodEffective(data){
  const state=data.effective_state||"UNVERIFIED";
  const descriptions={PAUSED:"Paused",WORKER_OFFLINE:"Worker offline",
    RECONCILIATION_PENDING:"Reconciliation pending",ORDER_PENDING:"Order pending",
    RISK_BLOCKED:"Risk blocked",AI_VETO:"AI veto",
    ARMED_WAITING_SIGNAL:"Armed · waiting for signal"};
  return {label:descriptions[state]||state.replaceAll("_"," "),
    detail:data.effective_detail||"Latest worker status unavailable",
    armed:data.policy_enabled===true,state};
}
async function loadRobinhoodDecisionEvidence(){
  const data=await request("/api/robinhood/status");
  const effective=robinhoodEffective(data);
  $("rh-decision-status").textContent=effective.label+" · "+effective.detail;
  $("rh-ai-connectivity").textContent="Shared Ollama: "+
    (data.worker?.ai_connection_status||"not checked")+" · Model: "+
    (data.worker?.ai_model||"unavailable")+
    " · AI gate: "+(data.worker?.ai_review_status||"not evaluated");
  const rows=Array.isArray(data.decision_evidence)?data.decision_evidence:[];
  $("rh-decision-rows").innerHTML=rows.length?rows.slice().reverse().map(x=>
    "<tr><td>"+esc(x.at||"—")+"</td><td>"+esc(x.signal||"—")+
    "</td><td>"+esc(x.ai_review_status||"—")+"</td><td>"+esc(x.ai_model||"—")+
    "</td><td>"+esc(x.ai_reason||"—")+"</td><td>"+esc(x.execution_status||"—")+
    "</td></tr>").join(""):'<tr><td colspan="6">No Robinhood worker decisions recorded yet</td></tr>';
}
async function loadRobinhoodExtras(){
  const [status,ai]=await Promise.all([request("/api/robinhood/status"),
    request("/api/ai/readiness")]);
  const effective=robinhoodEffective(status);
  $("rh-model-readiness").textContent="Provider: "+(ai.provider||"unknown")+
    " · Verification: "+(ai.status||"unknown")+
    " · Execution: "+effective.label;
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
      verified_broker_minimum_usd:"0",enabled:$("robinhood-risk-activate").checked};
    if(payload.enabled&&!window.confirm("Enable REAL-MONEY autonomous Robinhood crypto orders under these limits?"))return;
    await request("/api/robinhood/risk",{method:"POST",body:JSON.stringify(payload)});
    await loadRobinhoodRisk();
    toast("Robinhood trading permission updated: "+$("robinhood-risk-feedback").textContent);
  }catch(error){$("robinhood-risk-feedback").textContent=error.message;toast(error.message,true);}
  finally{button.disabled=false;}
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
    const diag=$("robinhood-signal-diagnostics");
    if(diag)diag.textContent=worker.signal_diagnostics||"No per-pair diagnostics recorded";
    const orderEl=$("robinhood-order-state");
    const executionEl=$("robinhood-execution-state");
    const when=worker.updated_at?new Date(worker.updated_at):null;
    const lastSeen=when&&!Number.isNaN(when.getTime())?when.toLocaleString():"not reported";
    if(scanEl)scanEl.textContent="Worker: "+(worker.worker||"not started")+
      " · Quotes checked: "+(Number.isInteger(worker.quotes_checked)?worker.quotes_checked:"unavailable")+
      " / "+(Number.isInteger(worker.pairs_checked)?worker.pairs_checked:"?")+
      " · Last checked: "+lastSeen+
      ". Quote checks are not trading signals.";
    if(orderEl)orderEl.textContent="Unreconciled Auto Trader intents: "+
      (Number.isInteger(worker.pending_order_intents)?worker.pending_order_intents:"unavailable")+
      ". Broker historical orders are separate from bot-confirmed fills.";
    if(executionEl)executionEl.textContent=effective.detail+
      " · Worker status: "+(worker.execution_status||"unavailable")+
      " · Risk: "+(worker.risk_check||"unavailable");
    const activityEl=$("robinhood-trade-activity");
    if(activityEl)activityEl.textContent=worker.last_order_confirmed?
      "Broker-confirmed bot fill recorded; inspect broker order history for details.":
      "No autonomous Robinhood fill verified. Broker historical orders do not prove bot execution.";
    const strategyEl=$("robinhood-strategy-status");
    if(strategyEl)strategyEl.textContent=
      "Scan: "+(worker.worker||"unavailable")+
      " · Signal: "+(worker.last_signal||"NOT_VERIFIED")+
      " · Trading permission: "+effective.label;
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
      positionState.textContent="Fetching Robinhood holdings and order history…";
      request("/api/robinhood/portfolio").then(portfolio=>{
        const box=$("robinhood-positions-list");
        if(box)box.replaceChildren();
        if(!portfolio.available){
          positionState.textContent=portfolio.reason||"Robinhood holdings unavailable";
          return;
        }
        const holdings=Number.isInteger(portfolio.position_count)?portfolio.position_count:0;
        if($("robinhood-holdings-stat"))$("robinhood-holdings-stat").textContent=String(holdings);
        if($("robinhood-orders-stat"))$("robinhood-orders-stat").textContent=Number.isInteger(portfolio.order_count)?String(portfolio.order_count):"—";
        const orders=Number.isInteger(portfolio.order_count)?portfolio.order_count:0;
        positionState.textContent=holdings+" holdings · "+orders+" broker order records";
        const total=$("robinhood-total-stat");
        if(total)total.textContent=portfolio.estimated_crypto_account_value_usd!=null?
          money(portfolio.estimated_crypto_account_value_usd):
          portfolio.known_holdings_value_usd!=null&&portfolio.cash_usd!=null?
          money(Number(portfolio.known_holdings_value_usd)+Number(portfolio.cash_usd))+"+":
          "Unavailable";
        const totalNote=$("robinhood-total-note");
        if(totalNote)totalNote.textContent=(portfolio.unpriced_holdings?.length?
          "Partial estimate · unpriced: "+portfolio.unpriced_holdings.join(", "):
          "Holdings + USD buying power; indicative quotes, not liquidation proceeds");
        if(box){
          const buying=document.createElement("p");
          buying.textContent="USD buying power: "+(portfolio.cash_usd==null?"unavailable":money(portfolio.cash_usd))+
            " · "+(portfolio.valuation_note||"Account valuation unavailable");
          box.append(buying);
          const table=document.createElement("table");
          const head=document.createElement("thead");
          head.innerHTML="<tr><th>Asset</th><th>Held quantity</th><th>Available to trade</th><th>Estimated USD value</th></tr>";
          table.append(head);
          const body=document.createElement("tbody");
          for(const holding of (Array.isArray(portfolio.holdings)?portfolio.holdings:[])){
            const row=document.createElement("tr");
            for(const value of [holding.symbol,holding.quantity,
                 holding.available_quantity??"Unavailable",
                 holding.market_value_usd==null?"Unavailable":money(holding.market_value_usd)]){
              const cell=document.createElement("td");cell.textContent=String(value);row.append(cell);
            }
            body.append(row);
          }
          if(!body.childNodes.length){
            const row=document.createElement("tr"),cell=document.createElement("td");
            cell.colSpan=4;cell.textContent="No broker-reported crypto holdings";row.append(cell);body.append(row);
          }
          table.append(body);box.append(table);
        }
      }).catch(()=>{positionState.textContent="Robinhood portfolio lookup unavailable";});
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
async function refreshAIReadiness(){
  const indicator=$("ai-readiness-indicator"), detail=$("ai-readiness-detail");
  if(!indicator||!detail)return;
  try{
    const info=await request("/api/ai/readiness");
    const claim=info.size_claim_meets_minimum===true;
    if(info.status==="metadata_verified" || info.status==="below_minimum" ||
       info.status==="unavailable_or_invalid_metadata"){
      indicator.textContent=info.status==="metadata_verified"?"SIZE VERIFIED":
        info.status==="below_minimum"?"BELOW 4B":"AI OFFLINE";
      detail.textContent=info.status==="metadata_verified"?
        "Ollama model size verified; response capability is not yet tested.":
        info.status==="below_minimum"?"Configured local AI model is below 4B.":
        "Unable to verify Ollama model; check model and network.";
      return;
    }
    indicator.textContent=info.status==="not_configured"?"UNCONFIGURED":
      info.status==="unverified_or_below_minimum"?"UNVERIFIED":"CHECK REQUIRED";
    detail.textContent=info.provider==="ollama"?
      (claim?"Model name claims 4B+; actual model and connection not yet verified.":"Local model is below 4B or size unknown; new minimum not yet enforced.") :
      info.status==="not_configured"?"No AI provider selected.":
      "Cloud provider selected; runtime readiness not verified.";
  }catch(err){
    indicator.textContent="UNKNOWN";
    detail.textContent="Could not retrieve AI readiness; do not assume AI is connected.";
  }
}
async function init(){
  bindEvents();
  try {
    const session=await request("/api/session");
    csrf=session.csrf;
    showApp();
    await refreshAll();
    await refreshAIReadiness();
    await checkForUpdate().catch(()=>{});
  } catch(_) { showLogin(); }
  setInterval(()=>{if(csrf) refreshAll().catch(err=>toast(err.message,true));},15000);
  setInterval(()=>{if(csrf) checkForUpdate().catch(()=>{});},60000);
  setInterval(()=>{if(csrf) refreshAIReadiness().catch(()=>{});},30000);
}
function bindEvents(){
  $("login-form").addEventListener("submit", async (ev)=>{
    ev.preventDefault();
    const btn=ev.currentTarget.querySelector("button");
    btn.disabled=true;
    $("login-error").textContent="";
    try{
      const data=await request("/api/login",{method:"POST",body:JSON.stringify({username:$("username").value,password:$("password").value})});
      csrf=data.csrf;showApp();await refreshAll();await refreshAIReadiness();await checkForUpdate().catch(()=>{});
    }catch(err){$("login-error").textContent=err.message;}finally{btn.disabled=false;}
  });
  $("profile-check-update").addEventListener("click",()=>checkForUpdate()
      .catch(err=>toast(err.message,true)));
  $("profile-password-form").addEventListener("submit",changeDashboardPassword);
  $("logout-btn").addEventListener("click",async()=>{
    try{await request("/api/logout",{method:"POST",body:"{}"});}catch(_){}
    csrf=null;showLogin();
  });
  $("refresh-btn").addEventListener("click",()=>refreshAll().catch(err=>toast(err.message,true)));
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
  $("robinhood-ai-models")?.addEventListener("click",()=>showView("local"));
  document.querySelectorAll(".workspace-tile:not(:disabled)").forEach(tile=>
    tile.addEventListener("click",()=>{
      if(!AVAILABLE_WORKSPACES.includes(tile.dataset.workspace))return;
      showView(tile.dataset.workspace==="paper"?"overview":
        tile.dataset.workspace==="robinhood_crypto"?"robinhood":"live");
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
function showView(view) {
  if(!["workspaces","live","decisions","live-risk","local","forecast","overview","trades","reviews","settings","profile","brokers","robinhood","robinhood-risk","robinhood-decisions","robinhood-models","robinhood-forecast"].includes(view))return;
  activeView=view;
  const liveViews=["live","decisions","live-risk","local","forecast"];
  const paperViews=["overview","trades","reviews","settings"];
  if(liveViews.includes(view))selectWorkspace("live");
  if(paperViews.includes(view))selectWorkspace("paper");
  const rhViews=["robinhood","robinhood-risk","robinhood-decisions","robinhood-models","robinhood-forecast"];
  if(rhViews.includes(view))selectWorkspace("robinhood_crypto");
  const context=liveViews.includes(view)?"live":paperViews.includes(view)?"paper":rhViews.includes(view)?"robinhood_crypto":null;
  $("sidebar-account-context").classList.toggle("hidden",context===null);
  if(context)$("sidebar-current-account").textContent=context==="live"?"Schwab live":context==="paper"?"Paper Trading":"Robinhood Crypto";
  $("live-nav-group").classList.toggle("hidden",context!=="live");
  $("paper-nav-group").classList.toggle("hidden",context!=="paper");
  $("robinhood-nav-group")?.classList.toggle("hidden",context!=="robinhood_crypto");
  document.querySelectorAll(".view").forEach(v=>v.classList.toggle("hidden",v.id!=="view-"+view));
  document.querySelectorAll(".nav-item").forEach(b=>b.classList.toggle("active",b.dataset.view===view));
  const titles={workspaces:"All accounts",live:"Schwab live",decisions:"Live AI evidence",
    "live-risk":"Live risk settings",local:"Local AI models",forecast:"Next session forecast",
    overview:"Paper simulator",trades:"Paper history",reviews:"Paper AI audit",
settings:"Paper risk settings",profile:"User profile",brokers:"Broker connections",robinhood:"Robinhood Crypto","robinhood-risk":"Robinhood risk settings",
    "robinhood-decisions":"Robinhood AI evidence","robinhood-models":"Robinhood AI models",
    "robinhood-forecast":"Crypto scan forecast"};
  $("breadcrumb-divider").classList.toggle("hidden",view==="workspaces");
  $("breadcrumb").textContent=titles[view];
  $("live-mode-banner").classList.toggle("hidden",!liveViews.includes(view));
  if(view==="trades" || view==="reviews") loadPage(view,page[view]).catch(err=>toast(err.message,true));
  if(view==="settings"){
    if(status) populateSettings(status.control.settings);
    loadPaperService().catch(err=>toast(err.message,true));
  }
  if(view==="local") loadLocalModels().catch(err=>toast(err.message,true));
  if(view==="forecast") loadForecast().catch(err=>toast(err.message,true));
  if(view==="brokers") loadBrokerWorkspace().catch(err=>toast(err.message,true));
  if(view==="robinhood") loadRobinhoodWorkspace().catch(err=>toast(err.message,true));
  if(view==="robinhood-risk") loadRobinhoodRisk().catch(err=>toast(err.message,true));
  if(view==="robinhood-decisions") loadRobinhoodDecisionEvidence().catch(err=>toast(err.message,true));
  if(view==="robinhood-models"||view==="robinhood-forecast") loadRobinhoodExtras().catch(err=>toast(err.message,true));
  if(view==="workspaces") refreshRobinhoodTile().catch(()=>{});
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
  $("server-pill").classList.toggle("offline",!active);
  $("server-pill").innerHTML=`<span class="live-dot"></span> ${active?"Monitor online":"Monitor offline"}`;
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
