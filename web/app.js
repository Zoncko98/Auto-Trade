"use strict";

const $ = (id) => document.getElementById(id);
const money = (v) => new Intl.NumberFormat("en-US", {style:"currency",currency:"USD",minimumFractionDigits:2,maximumFractionDigits:2}).format(Number(v)||0);
const intNum = (v) => new Intl.NumberFormat("en-US").format(Number(v)||0);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
const pct = (v) => `${Number(v)||0}%`;
let csrf = null;
let status = null;
let activeView = "live";
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
  $("app").classList.add("hidden");
  $("login-screen").classList.remove("hidden");
  $("password").value="";
  $("password").focus();
}
function showApp(){
  $("login-screen").classList.add("hidden");
  $("app").classList.remove("hidden");
}
async function init(){
  bindEvents();
  try {
    const session=await request("/api/session");
    csrf=session.csrf;
    showApp();
    await refreshAll();
  } catch(_) { showLogin(); }
  setInterval(()=>{if(csrf) refreshAll().catch(err=>toast(err.message,true));},15000);
}
function bindEvents(){
  $("login-form").addEventListener("submit", async (ev)=>{
    ev.preventDefault();
    const btn=ev.currentTarget.querySelector("button");
    btn.disabled=true;
    $("login-error").textContent="";
    try{
      const data=await request("/api/login",{method:"POST",body:JSON.stringify({password:$("password").value})});
      csrf=data.csrf;showApp();await refreshAll();
    }catch(err){$("login-error").textContent=err.message;}finally{btn.disabled=false;}
  });
  $("logout-btn").addEventListener("click",async()=>{
    try{await request("/api/logout",{method:"POST",body:"{}"});}catch(_){}
    csrf=null;showLogin();
  });
  $("refresh-btn").addEventListener("click",()=>refreshAll().catch(err=>toast(err.message,true)));
  document.querySelectorAll("[data-view]").forEach(button=>button.addEventListener("click",()=>showView(button.dataset.view)));
  document.querySelectorAll("[data-mode]").forEach(button=>button.addEventListener("click",()=>setMode(button.dataset.mode)));
  $("settings-form").addEventListener("submit",saveSettings);
  $("settings-form").querySelectorAll("input").forEach(field=>field.addEventListener("input",updatePreview));
  for(const kind of ["trades","reviews"]){
    $(kind+"-prev").addEventListener("click",()=>loadPage(kind,Math.max(1,page[kind]-1)));
    $(kind+"-next").addEventListener("click",()=>loadPage(kind,page[kind]+1));
  }
  $("export-trades").addEventListener("click",exportTrades);
}
function showView(view) {
  if(!["live","local","overview","trades","reviews","settings"].includes(view))return;
  activeView=view;
  document.querySelectorAll(".view").forEach(v=>v.classList.toggle("hidden",v.id!==`view-${view}`));
  document.querySelectorAll(".nav-item").forEach(b=>b.classList.toggle("active",b.dataset.view===view));
  const titles={live:"Schwab live",local:"Local AI models",overview:"Paper simulator",trades:"Paper history",reviews:"Paper AI audit",settings:"Paper risk settings"};
  $("breadcrumb").textContent=titles[view];
  if(view==="trades" || view==="reviews") loadPage(view,page[view]).catch(err=>toast(err.message,true));
  if(view==="settings" && status) populateSettings(status.control.settings);
  if(view==="local") loadLocalModels().catch(err=>toast(err.message,true));
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
    renderOverview(response,performance.points||[],trades.items||[]);
    renderLiveView(live);
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
  else if(!r.ai_model_configured)message=["AI model not configured","All new paper-buy candidates are blocked until a model is connected. No live market feed is connected either."];
  else message=["No live market feed connected","The strategy needs valid timestamped prices; the AI model configuration has not been live-tested."];
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
    $("trades-table").innerHTML=payload.items.length?payload.items.map(t=>{
      const pnl=Number(t.realized_pnl||0);
      const reason=t.reason||"No rationale recorded (legacy trade)";
      const ai=t.ai_review?`<div class="muted-cell">AI: ${esc(t.ai_review.model||"unknown")} · ${esc(t.ai_review.reason||"")}</div>`:"";
      return `<tr>
        <td>${esc(t.timestamp||"—")}</td><td class="symbol">${esc(t.symbol)}</td>
        <td><span class="pill ${t.action==="PAPER_BUY"?"buy":"sell"}">${esc(t.action)}</span></td>
        <td>${esc(t.quantity)}</td><td>${money(t.price)}</td>
        <td class="${pnl>=0?"green":"red"}">${t.action==="PAPER_SELL"?money(pnl):"—"}</td>
        <td class="reason">${esc(reason)}${ai}</td></tr>`;
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
function toCsvCell(v){
  let s=String(v??"");
  if(/^[=+@\-\t\r]/.test(s))s="'"+s;
  return '"'+s.replaceAll('"','""')+'"';
}
async function exportTrades(){
  const button=$("export-trades");button.disabled=true;button.textContent="Preparing CSV…";
  try{
    const records=[];
    for(let p=1;p<=5000;p++){
      const response=await request(`/api/trades?page=${p}&limit=100`);
      records.push(...response.items);
      if(p*100>=response.total)break;
    }
    const keys=["timestamp","symbol","action","quantity","price","realized_pnl","reason","ai_decision","ai_model","ai_reason"];
    const csv=[keys.join(","),...records.map(r=>{
      const values=[r.timestamp,r.symbol,r.action,r.quantity,r.price,r.realized_pnl,
        r.reason,r.ai_review?.approved?"APPROVE":r.ai_review?"REJECT":"",r.ai_review?.model,r.ai_review?.reason];
      return values.map(toCsvCell).join(",");
    })].join("\r\n");
    const blob=new Blob([csv],{type:"text/csv;charset=utf-8"});
    const url=URL.createObjectURL(blob),link=document.createElement("a");
    link.href=url;link.download="tradepilot-trades-"+new Date().toISOString().slice(0,10)+".csv";
    document.body.appendChild(link);link.click();link.remove();URL.revokeObjectURL(url);
    toast(`Exported ${records.length} paper trades.`);
  }catch(err){toast(err.message,true);}finally{button.disabled=false;button.textContent="↓ Export all trades";}
}
document.addEventListener("DOMContentLoaded",init);
