"use strict";

// Live and local-AI views share the existing authenticated, CSRF-protected
// dashboard connection. No cloud provider keys or Schwab secrets enter JS.
let lastLive = null;
let installedLocalModels = [];

function present(v) {
  return v === undefined || v === null || v === "" ? "—" : String(v);
}
function formatBrokerDate(v) {
  if (!v) return "—";
  const dt = new Date(v);
  return Number.isFinite(dt.getTime()) ? dt.toLocaleString("en-US", {timeZone:"UTC",hour12:false})+" UTC" : present(v);
}

function renderLiveView(data) {
  lastLive=data;
  const armed=data.worker_online && data.armed;
  const paused=data.order_permission !== "running";
  const active=armed && !paused && !data.journal_halted;
  const heartbeat=data.heartbeat_age_sec;
  $("live-worker-mode").textContent=!armed?"Not armed":data.journal_halted?"Halted":paused?"Paused":"Running";
  $("live-worker-mode").className="mode-tag "+(active?"running":paused?"paused":"stopped");
  $("live-execution-pill").textContent=active?"LIVE · AUTOMATED":armed?"WORKER ACTIVE · PAUSED":"NOT ARMED";
  $("live-mode-banner").textContent=active?"LIVE · CASH ONLY":"LIVE ORDERS OFF";
  $("side-live-status").textContent=active?"ACTIVE":armed?"PAUSED":"OFF";
  $("server-pill").classList.toggle("offline",!data.worker_online);
  $("server-pill").innerHTML='<span class="live-dot"></span> '+(data.worker_online?"Schwab worker online":"Live worker offline");
  $("live-resume-btn").disabled=!armed||active||data.journal_halted;
  $("live-pause-btn").disabled=!armed||paused;
  $("live-order-permission").textContent=present(data.order_permission);
  $("live-heartbeat").textContent=heartbeat===null?"No heartbeat":heartbeat+" seconds ago";
  $("live-current-model").textContent=present(data.selected_model);
  $("live-local-inference").textContent=data.selected_model?"Local Ollama: "+data.selected_model:"Not selected";

  const a=data.account||{};
  const hasSnapshot=Boolean(a.at);
  $("live-equity").textContent=hasSnapshot?money(a.equity):"—";
  $("live-cash").textContent=hasSnapshot?money(a.cash):"—";
  const positions=a.positions||{};
  const holdings=Object.entries(positions);
  $("live-holdings").textContent=hasSnapshot?String(holdings.length):"—";
  $("live-holdings-detail").textContent=hasSnapshot
    ? holdings.length?holdings.map(([symbol,quantity])=>symbol+" · "+quantity+" shares").join(", "):"No open holdings"
    :"Awaiting brokerage account snapshot";
  $("live-snapshot-age").textContent=hasSnapshot?"Broker snapshot: "+formatBrokerDate(a.at):"No read-only brokerage snapshot yet";
  $("live-order-total").textContent=intNum(data.order_count);
  $("live-nav-count").textContent=intNum(data.order_count);

  const items=data.orders||[];
  const decisions=data.decisions||[];
  const bySignal=(order)=>decisions.find(e=>e.symbol===order.symbol&&e.candle===order.candle);
  $("live-orders-table").innerHTML=items.length?items.map(o=>{
    const buy=o.action==="BUY";
    const state=present(o.state);
    const filled=o.filled_price!==null&&o.filled_price!==undefined;
    const gross=o.gross_realized_pnl;
    const evidence=bySignal(o);
    return `<tr>
      <td>${esc(formatBrokerDate(o.created_at))}</td>
      <td class="symbol">${esc(o.symbol)}</td>
      <td><span class="pill ${buy?"buy":"sell"}">${esc(o.action)}</span></td>
      <td>${esc(o.quantity)}</td>
      <td>${o.limit_price!=null?money(o.limit_price):"—"}</td>
      <td>${filled?money(o.filled_price):"Not verified"}</td>
      <td class="${gross==null?"muted-cell":gross>=0?"green":"red"}">${gross==null?"—":money(gross)}</td>
      <td>${esc(state)}</td>
      <td class="reason">${esc(o.reason||"No rationale available")}
        ${evidence?`<div class="subdued-evidence">Audit: ${esc(evidence.decision)} · ${esc(evidence.model||"rule-based")}</div>`:""}</td>
      <td><button class="btn secondary tiny" data-export-live-index="${o.index}">↓ XLSX</button></td></tr>`;
  }).join(""):'<tr><td colspan="10" class="empty-row">No real Schwab orders have been submitted by this worker.</td></tr>';
  renderLiveDecisions(decisions);
  $("live-order-count-note").textContent=data.order_count
    ?data.order_count+" real brokerage order records; the broker may not have filled every accepted order."
    :"No real orders recorded. SPYD is still awaiting the authorized initial sell.";
  let title,text;
  if (data.journal_halted){
    title="Trading halted for reconciliation";
    text=present(data.halt_reason)+". Do not restart the worker until the broker order is reconciled.";
  } else if(!armed){
    title="Real-money worker is not running";
    text="Local AI can be configured now, but live orders require verified worker activation in TrueNAS.";
  } else if(paused){
    title="Live order submissions paused";
    text="The worker remains connected for monitoring. No new orders will be submitted until allowed.";
  } else {
    title="Live worker is armed for autonomous cash-only trades";
    text="It trades only during its permitted U.S. regular-market session. A positive AI classification does not guarantee returns.";
  }
  $("live-warning-title").textContent=title;
  $("live-warning-text").textContent=text;
}

function safeNewsUrl(value){
  try{
    const u=new URL(value);
    return u.protocol==="https:"&&u.hostname==="news.google.com" ? u.href : "";
  }catch(_){return "";}
}
function renderLiveDecisions(items){
  $("live-decisions-count").textContent=items.length+" recorded evaluations";
  $("live-decisions-table").innerHTML=items.length?items.map(e=>{
    const details=e.signals&&typeof e.signals==="object"
      ? Object.entries(e.signals).map(([k,v])=>esc(k)+": "+esc(v)).join(" · "):"—";
    const news=Array.isArray(e.headlines)?e.headlines:[];
    const sources=news.map(n=>{
      const url=safeNewsUrl(n.url);
      const title=esc(n.title||"Untitled headline");
      return `<li><strong>${esc(n.source||"Unknown publisher")}</strong> · ${title}
        <span class="muted-cell">${esc(n.published_at||"")}</span>
        ${url?`<a href="${esc(url)}" rel="noopener noreferrer" target="_blank">Source</a>`:""}</li>`;
    }).join("");
    const ai=[e.sentiment!=null?"sentiment "+e.sentiment:"",
              e.impact!=null?"impact "+e.impact:"",
              e.catalyst?"catalyst: "+e.catalyst:"",
              e.downside_risk?"risk: "+e.downside_risk:""].filter(Boolean).join(" · ");
    const evidence=`<details><summary>View sources &amp; signals</summary>
       <div class="evidence-expanded"><p><strong>Market:</strong> ${details}</p>
       <p><strong>Model output:</strong> ${esc(ai||"Rule-based / no AI model used")}</p>
       ${sources?`<ol>${sources}</ol>`:"<p>No source headlines were saved for this evaluation.</p>"}
       </div></details>`;
    const yes=e.decision==="ORDER_INTENT";
    return `<tr>
      <td>${esc(formatBrokerDate(e.at))}</td>
      <td class="symbol">${esc(e.symbol)}</td>
      <td><span class="pill ${yes?"approve":"reject"}">${esc(e.decision)}</span></td>
      <td>${esc(e.model||"—")}</td>
      <td class="reason">${esc(e.summary||"No summary saved")}</td>
      <td class="reason">${evidence}</td></tr>`;
  }).join(""):'<tr><td colspan="6" class="empty-row">No live evaluations yet. The next eligible market session will generate auditable decision summaries.</td></tr>';
}
const LIVE_RISK_FIELDS=[
  "allocation_pct","max_order_usd","max_position_pct","max_daily_loss",
  "max_open_positions","max_buys_per_day","max_orders_per_day",
  "daily_growth_target_pct"
];
function populateLiveRisk(live){
  if(!live||!live.risk||!live.risk.settings)return;
  if(live.risk_error){
    $("live-risk-message").textContent="Risk configuration invalid: "+live.risk_error;
    $("live-risk-save").disabled=true;
    return;
  }
  $("live-risk-save").disabled=false;
  const settings=live.risk.settings;
  LIVE_RISK_FIELDS.forEach(k=>{$("live-"+k).value=settings[k];});
  updateLiveRiskPreview();
}
function liveRiskValues(){
  const values={};
  for(const k of LIVE_RISK_FIELDS){
    const control=$("live-"+k);
    values[k]=["max_open_positions","max_buys_per_day","max_orders_per_day"].includes(k)
      ?Number.parseInt(control.value,10):Number(control.value);
  }
  return values;
}
function updateLiveRiskPreview(){
  const values=liveRiskValues();
  const cash=Math.max(0,Number(lastLive?.account?.cash)||0);
  const allocation=Math.max(0,Number(values.allocation_pct)||0)/100;
  const cap=Math.min(25,cash*allocation,
    Math.max(0,Number(values.max_order_usd)||0),
    Math.max(0,Number(values.max_position_pct)||0));
  $("live-risk-order-preview").textContent=money(cap);
  $("live-risk-cash-preview").textContent=money(cash);
  $("live-risk-loss-preview").textContent=money(values.max_daily_loss);
  $("live-risk-orders-preview").textContent=values.max_orders_per_day+" per day";
  $("live-risk-target-preview").textContent=values.daily_growth_target_pct+"% (reporting only)";
}
async function saveLiveRisk(ev){
  ev.preventDefault();
  if(!lastLive||lastLive.risk_error)return toast("Live risk settings are invalid; refresh.",true);
  if(!$("live-risk-form").reportValidity())return;
  const settings=liveRiskValues(),previous=lastLive.risk.settings;
  if(!Number.isInteger(settings.max_open_positions)
    ||!Number.isInteger(settings.max_buys_per_day)
    ||!Number.isInteger(settings.max_orders_per_day)
    ||settings.max_orders_per_day<settings.max_buys_per_day)
    return toast("Invalid daily order/position limits.",true);
  const increasing=LIVE_RISK_FIELDS.some(k=>k!=="daily_growth_target_pct"&&settings[k]>previous[k]);
  if(increasing&&!confirm("This raises at least one REAL-MONEY trading limit within its hard cap. Continue?"))return;
  const save=$("live-risk-save");save.disabled=true;
  try{
    const reply=await request("/api/live/risk",{method:"POST",
      body:JSON.stringify({revision:lastLive.risk.revision,settings})});
    lastLive.risk=reply.risk;
    $("live-risk-message").textContent="Saved. The live worker applies these limits on its next scan.";
    toast("Live risk settings saved.");
    await refreshAll();
  }catch(err){
    toast(err.message,true);$("live-risk-message").textContent=err.message;
  }finally{save.disabled=false;}
}

async function loadLocalModels(){
  $("local-server-status").textContent="Checking…";
  let data;
  try{
    data=await request("/api/local/models");
  }catch(err){
    $("local-server-status").textContent="Offline or unavailable";
    $("local-model-select").innerHTML='<option value="">No local models available</option>';
    $("local-model-save").disabled=true;
    $("local-model-details").textContent=err.message;
    throw err;
  }
  installedLocalModels=data.models||[];
  const list=$("local-model-select");
  const current=list.value;
  list.textContent="";
  for(const entry of installedLocalModels){
    const option=document.createElement("option");
    option.value=entry.name;
    option.disabled=!entry.selectable;
    option.textContent=entry.name+" · "+entry.size_mb+" MB"+(entry.parameters?" · "+entry.parameters:"")+
      (entry.selectable?"":" (too large for NAS budget)");
    list.appendChild(option);
  }
  if(!list.options.length){
    const option=document.createElement("option");
    option.value="";option.textContent="No local Ollama models downloaded";
    list.appendChild(option);
  }
  const selected=installedLocalModels.find(x=>x.name===current&&x.selectable)?current:data.selected;
  const found=installedLocalModels.find(x=>x.name===selected&&x.selectable);
  list.value=found?selected:(installedLocalModels.find(x=>x.selectable)?.name||"");
  $("local-server-status").textContent="Connected · "+installedLocalModels.length+" installed";
  $("local-saved-model").textContent=present(data.selected);
  $("local-model-save").disabled=!list.value||list.value===data.selected;
  updateLocalModelDetails();
}
function updateLocalModelDetails(){
  const value=$("local-model-select").value;
  const entry=installedLocalModels.find(x=>x.name===value);
  $("local-model-details").textContent=entry
     ?`This installed model uses approximately ${entry.size_mb} MB of disk weights; the local container is limited to 2 CPU cores and 2.5 GB of RAM. Selection affects future news evaluations only.`
     :"Select an installed model that fits the NAS budget.";
  $("local-model-save").disabled=!entry||!entry.selectable||value===$("local-saved-model").textContent;
}
async function saveLocalModel(ev){
  ev.preventDefault();
  const select=$("local-model-select"),button=$("local-model-save");
  const model=select.value;
  if(!installedLocalModels.some(m=>m.name===model&&m.selectable))
    return toast("Choose an installed small local model.",true);
  button.disabled=true;
  try{
    await request("/api/local/model",{method:"POST",body:JSON.stringify({model})});
    $("local-model-message").textContent=model+" selected for the next local AI evaluation.";
    toast("Local model selection saved.");
    await loadLocalModels();
    await refreshAll();
  }catch(err){toast(err.message,true);$("local-model-message").textContent=err.message;}
  finally{button.disabled=false;updateLocalModelDetails();}
}
async function livePermission(mode){
  if(!lastLive||!lastLive.armed||!lastLive.worker_online)return;
  const msg=mode==="running"
    ?"Allow the live worker to submit real Schwab orders during permitted market hours?"
    :"Pause new Schwab order submissions? Accepted broker orders will not be canceled automatically.";
  if(!window.confirm(msg))return;
  const button=mode==="running"?$("live-resume-btn"):$("live-pause-btn");
  button.disabled=true;
  try{
    await request("/api/live/mode",{method:"POST",body:JSON.stringify({mode})});
    toast(mode==="running"?"Autonomous order submission permitted.":"Order submissions paused.");
    await refreshAll();
  }catch(err){toast(err.message,true);}
}
document.addEventListener("DOMContentLoaded",()=>{
  $("local-model-select").addEventListener("change",updateLocalModelDetails);
  $("local-model-form").addEventListener("submit",saveLocalModel);
  $("live-resume-btn").addEventListener("click",()=>livePermission("running"));
  $("live-pause-btn").addEventListener("click",()=>livePermission("paused"));
  $("live-risk-form").addEventListener("submit",saveLiveRisk);
  $("live-risk-form").querySelectorAll("input").forEach(input=>
    input.addEventListener("input",updateLiveRiskPreview));
});
