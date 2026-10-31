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
  // Use the local installed version, not the remote GitHub release.
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
  $("export-live-trades").addEventListener("click",()=>downloadWorkbook(
    "/api/live/export.xlsx","autotrader-live-trades.xlsx",$("export-live-trades")));
  $("export-live-evidence").addEventListener("click",()=>downloadWorkbook(
    "/api/live/export.xlsx","autotrader-live-evidence.xlsx",$("export-live-evidence")));
  $("workspace-select").addEventListener("change",event=>{
    showView(event.target.value==="paper"?"overview":"live");
  });
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
  if(!["live","decisions","live-risk","local","forecast","overview","trades","reviews","settings","profile","brokers"].includes(view))return;
  activeView=view;
  const workspace=["profile","brokers"].includes(view)?$("workspace-select").value:(["live","decisions","live-risk","local","forecast"].includes(view)?"live":"paper");
  $("workspace-select").value=workspace;
  $("workspace-description").textContent=workspace==="live"
    ?"Real Schwab account · cash only":"Simulated account · no real orders";
  $("live-nav-group").classList.toggle("hidden",workspace!=="live");
  $("paper-nav-group").classList.toggle("hidden",workspace!=="paper");
  document.querySelectorAll(".view").forEach(v=>v.classList.toggle("hidden",v.id!==`view-${view}`));
  document.querySelectorAll(".nav-item").forEach(b=>b.classList.toggle("active",b.dataset.view===view));
  const titles={live:"Schwab live",decisions:"Live AI evidence","live-risk":"Live risk settings",
    local:"Local AI models",forecast:"Next session forecast",overview:"Paper simulator",trades:"Paper history",
    reviews:"Paper AI audit",settings:"Paper risk settings",profile:"User profile",
    brokers:"Broker connections"};
  $("breadcrumb").textContent=titles[view];
  if(view==="trades" || view==="reviews") loadPage(view,page[view]).catch(err=>toast(err.message,true));
  if(view==="settings" && status) populateSettings(status.control.settings);
  if(view==="local") loadLocalModels().catch(err=>toast(err.message,true));
  if(view==="forecast") loadForecast().catch(err=>toast(err.message,true));
  if(view==="brokers") loadBrokerWorkspace().catch(err=>toast(err.message,true));
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
document.addEventListener("DOMContentLoaded",init);


async function changeDashboardPassword(ev){
  ev.preventDefault();
  const current=$("profile-current").value;
  const next=$("profile-new").value;
  const confirmation=$("profile-confirm").value;
  const feedback=$("profile-message");
  feedback.textContent="";
  if(next!==confirmation){feedback.textContent="New passwords do not match.";return;}
  if(next.length<20){feedback.textContent="Use at least 20 characters.";return;}
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
