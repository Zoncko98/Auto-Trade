"use strict";
// Read-only broker status plus authenticated paper-only simulation controls.
document.addEventListener("DOMContentLoaded",()=>{
  const target=document.getElementById("v2-foundation-status");
  const health=document.getElementById("v2-adapter-health");
  if(!target)return;
  function showAdapters(rows,market,diagnostics){
    if(!health)return;
    health.replaceChildren();
    if(!Array.isArray(rows)||!rows.length){
      health.textContent="No verified read-only broker observations loaded.";return;
    }
    const display={schwab:"Schwab stocks",webull:"Webull stocks",
      robinhood_crypto:"Robinhood crypto",paper:"Paper trading"};
    const explanations=new Map(
      (Array.isArray(diagnostics)?diagnostics:[]).filter(d=>
        d&&typeof d.broker==="string").map(d=>[d.broker,d]));
    for(const row of rows){
      if(!row || typeof row!=="object")continue;
      const line=document.createElement("div");
      line.className="readiness-item";
      const heading=document.createElement("strong");
      heading.textContent=display[row.broker]||"Unknown account";
      line.append(heading);
      const body=document.createElement("span");
      const state=String(row.worker_state||"OFFLINE");
      const auth=String(row.auth||"UNVERIFIED");
      const permission=row.permission_armed
        ?(state==="ONLINE"&&auth==="CONNECTED"?"V1 permission armed":
          "V1 authorized in settings; execution unavailable")
        :"V1 disarmed";
      const userAction=auth==="REAUTH_REQUIRED"
        ?" · Action: Reconnect Schwab under Broker connections"
        :"";
      const value=(key,label)=>row.read_verified&&row[key]!==null&&
        row[key]!==undefined?label+" $"+String(row[key]):null;
      const values=[value("cash_usd","Cash"),value("equity_usd","Equity"),
        value("buying_power_usd","Buying power"),value("entry_headroom_usd","Entry headroom")]
          .filter(Boolean).join(" · ");
      const feed=market&&market[row.broker]?market[row.broker]:null;
      const quote=feed?String(feed.state||"UNVERIFIED"):"UNVERIFIED";
      body.textContent=state+" · "+auth+" · "+permission+
        " · "+String(row.reason_code||"UNVERIFIED")+
        (values?" · "+values:" · Values unavailable")+
        " · Market: "+quote+" (read-only)"+userAction;
      line.append(body);
      const issue=explanations.get(row.broker);
      if(issue && issue.execution_path==="V2_READ_ONLY_NO_ORDER_AUTHORITY"){
        const note=document.createElement("small");
        note.className="muted";
        const code=String(issue.first_issue||"NOT_VERIFIED");
        const action=String(issue.user_action||"Check Diagnostics");
        note.textContent="V2 why no trade: "+code+
          " · Next: "+action+
          " · V2 signal, AI, risk and order reconciliation are not verified";
        line.append(note);
      }
      health.append(line);
    }
  }
  async function readV2Status(){
    try{
      const response=await fetch("/api/v2/status",{
        credentials:"same-origin",cache:"no-store",headers:{"Accept":"application/json"}});
      if(response.status===401){
        target.textContent="Sign in to inspect V2.";return;
      }
      if(!response.ok)throw Error("V2 status unavailable");
      const data=await response.json();
      const flag=data.feature_enabled?"Core flag enabled for paper/replay":
        "Core flag disabled; fresh V2 crypto paper follows the Paper Trading setting";
      const store=data.store||"Unavailable";
      target.textContent="V2 "+String(data.version||"experimental")+
        " · "+flag+" · Live broker authority: OFF"+
        " · Event store: "+store+
        " · Persisted intents: "+Number(data.intents||0)+
        " · Unresolved: "+Number(data.unresolved||0)+
        " · Recorded historical paper replay: on demand, broker-independent";
      showAdapters(data.broker_adapters,data.market_sources,data.readiness_diagnostics);
      void readFreshPaperStatus();
      void readRecordedReplay();
    }catch(_error){
      target.textContent="V2 status unavailable. V1 broker operation is unchanged.";
      if(health)health.textContent="Read-only broker adapter evidence unavailable.";
    }
  }

  const freshNode=document.getElementById("v2-paper-fresh-report");
  async function readFreshPaperStatus(){
    if(!freshNode)return;
    try{
      const response=await fetch("/api/v2/paper-fresh",{
        credentials:"same-origin",cache:"no-store",
        headers:{"Accept":"application/json"}});
      if(!response.ok)throw Error("Fresh-paper worker status unavailable");
      const data=await response.json();
      freshNode.replaceChildren();
      const list=Array.isArray(data.reports)?data.reports:[];
      for(const report of list){
        if(!report || !["BTCUSD","ETHUSD"].includes(report.symbol))continue;
        const item=document.createElement("p");
        const state=String(report.scan_state||"NOT_SCANNED");
        const bars=Number(report.closed_bars||0);
        const target=Number(report.ready_closed_bars||9);
        let text=report.symbol+" · "+state+
           " · "+bars+"/"+target+" real closed candles";
        if(report.reason)text+=" · "+String(report.reason);
        if(report.last_quote_at)text+=" · Quote "+String(report.last_quote_at);
        if(report.heartbeat_age_sec!==undefined &&
           report.heartbeat_age_sec!==null)
           text+=" · Heartbeat "+Number(report.heartbeat_age_sec)+"s";
        if(report.virtual_equity!==undefined){
          text+=" · Simulated equity $"+String(report.virtual_equity)+
             " · Cash $"+String(report.virtual_cash);
          const journal=report.journal||{};
          text+=" · Persisted simulated intents "+Number(journal.intents||0)+
             " · Unresolved "+Number(journal.unresolved||0);
        }
        item.textContent=text;
        freshNode.append(item);
      }
      if(freshNode.childElementCount===0)
        freshNode.textContent="No verified V2 paper worker observations yet.";
    }catch(_error){
      freshNode.textContent="Fresh-paper worker status unavailable. No live orders are affected.";
    }
  }

  const replaySelect=document.getElementById("v2-replay-symbol");
  const replayRun=document.getElementById("v2-replay-run");
  const replayStatus=document.getElementById("v2-replay-status");
  const replayReport=document.getElementById("v2-replay-report");
  let replayBusy=false;

  function showRecordedReport(report){
    if(!replayReport)return;
    replayReport.replaceChildren();
    if(!report || report.simulated_only!==true ||
       report.live_orders_submitted!==0 || !report.run_id)return;
    const message=document.createElement("p");
    const journal=report.journal&&typeof report.journal==="object"?report.journal:{};
    message.textContent="Historical synthetic replay · "+String(report.symbol||"")+
      " · Closed candles: "+Number(report.candles||0)+
      " · Strategy signals: "+Number(report.signals||0)+
      " · Simulated fills: "+Number(report.fills||0)+
      " · Blocked: "+Number(report.blocked||0)+
      " · Net after assumed costs: $"+String(report.net_pnl_after_simulated_costs||"unknown")+
      " · Final simulated equity: $"+String(report.final_equity||"unknown")+
      " · V2 intents: "+Number(journal.intents||0)+
      " · Unresolved intents: "+Number(journal.unresolved||0)+
      " · No live orders, broker quotes or AI reviews";
    replayReport.append(message);
    const detail=document.createElement("small");
    detail.className="muted";
    const assumptions=report.assumptions||{};
    detail.textContent="Tape "+String(report.recording_start||"unknown")+
      " through "+String(report.recording_end||"unknown")+
      " · Synthetic spread "+String(assumptions.synthetic_spread_bps||"?")+" bps"+
      " · Simulated fees "+String(assumptions.fee_bps||"?")+" bps"+
      " · Simulated slippage "+String(assumptions.slippage_bps||"?")+" bps"+
      " · Replay ID "+String(report.run_id).slice(0,12);
    replayReport.append(detail);
  }

  async function readRecordedReplay(){
    if(!replaySelect || !replayRun)return;
    try{
      const response=await fetch("/api/v2/replay",{
        credentials:"same-origin",cache:"no-store",headers:{"Accept":"application/json"}});
      if(response.status===401)throw Error("Sign in to view recorded replay");
      if(!response.ok)throw Error("Historical replay status unavailable");
      const data=await response.json();
      const former=replaySelect.value;
      replaySelect.replaceChildren();
      const list=Array.isArray(data.symbols)?data.symbols.filter(
        entry=>entry&&entry.replayable===true&&typeof entry.symbol==="string"):[];
      for(const entry of list){
        const option=document.createElement("option");
        option.value=entry.symbol;
        option.textContent=entry.symbol+" · "+entry.asset_class+
          " · "+Number(entry.closed_bars)+" closed candles";
        replaySelect.append(option);
      }
      if(list.some(entry=>entry.symbol===former))replaySelect.value=former;
      replaySelect.disabled=list.length===0||replayBusy;
      replayRun.disabled=list.length===0||replayBusy;
      if(replayStatus && !replayBusy){
        replayStatus.textContent=list.length
          ?"Recorded closed candles available for an explicitly triggered paper replay."
          :"No replayable recorded candles: "+String(data.state||"UNAVAILABLE");
      }
      showRecordedReport(data.last_report);
    }catch(err){
      replaySelect.disabled=true;
      replayRun.disabled=true;
      if(replayStatus)replayStatus.textContent=err.message||"Historical replay unavailable";
    }
  }

  async function submitRecordedReplay(){
    if(!replaySelect||!replayRun||replayBusy||!replaySelect.value)return;
    const symbol=replaySelect.value;
    replayBusy=true;
    replayRun.disabled=true;
    replaySelect.disabled=true;
    if(replayStatus)replayStatus.textContent="Running historical, broker-independent simulation…";
    try{
      const auth=await fetch("/api/session",{
        credentials:"same-origin",cache:"no-store",headers:{"Accept":"application/json"}});
      if(!auth.ok)throw Error("Sign in again to run historical replay");
      const session=await auth.json();
      if(typeof session.csrf!=="string"||session.csrf.length<16)throw Error("Session expired");
      const response=await fetch("/api/v2/replay/run",{
        method:"POST",credentials:"same-origin",cache:"no-store",
        headers:{"Content-Type":"application/json","Accept":"application/json",
                 "X-CSRF-Token":session.csrf},
        body:JSON.stringify({symbol})
      });
      const report=await response.json();
      if(!response.ok)throw Error(String(report.error||"Historical simulation failed"));
      if(report.simulated_only!==true||report.live_orders_submitted!==0)
        throw Error("Simulation did not prove paper-only execution");
      showRecordedReport(report);
      if(replayStatus)replayStatus.textContent="Historical paper replay complete. All orders were simulated.";
    }catch(err){
      if(replayStatus)replayStatus.textContent=err.message||"Historical replay unavailable";
    }finally{
      replayBusy=false;
      replaySelect.disabled=false;
      replayRun.disabled=false;
    }
  }
  replayRun?.addEventListener("click",submitRecordedReplay);

  document.getElementById("v2-status-refresh")?.addEventListener("click",readV2Status);
  document.getElementById("operations-refresh")?.addEventListener("click",readV2Status);
  document.querySelector('[data-view="operations"]')?.addEventListener("click",readV2Status);
});
