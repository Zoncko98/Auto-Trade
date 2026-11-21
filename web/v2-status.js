"use strict";
// Read-only broker status plus authenticated paper-only simulation controls.
document.addEventListener("DOMContentLoaded",()=>{
  const target=document.getElementById("v2-foundation-status");
  const health=document.getElementById("v2-adapter-health");
  const cutover=document.getElementById("v2-cutover-status");
  if(!target)return;
  function showCutover(report){
    if(!cutover)return;
    cutover.replaceChildren();
    const intro=document.createElement("strong");
    intro.textContent="V2 live-account migration preflight · read-only · no automatic cutover";
    cutover.append(intro);
    if(!report||report.live_order_authority!==false||
       report.automatic_cutover_allowed!==false||!Array.isArray(report.accounts)){
      const failure=document.createElement("p");
      failure.textContent="Cutover evidence unavailable. V2 live orders remain disabled.";
      cutover.append(failure);return;
    }
    const titles={schwab:"Schwab",webull:"Webull",
      robinhood_crypto:"Robinhood Crypto",paper:"Paper"};
    for(const item of report.accounts){
      if(!item||!Object.hasOwn(titles,item.broker))continue;
      const section=document.createElement("p");
      const risk=item.risk||{},journal=item.journal||{};
      const local=journal.local_evidence||{};
      const envelope=item.risk_envelope||{};
      const limits=risk.limits||{};
      const values=Object.entries(limits).slice(0,7).map(([k,v])=>
        k.replaceAll("_"," ")+"="+String(v)).join(" · ");
      const state=item.broker==="paper"?"Simulation only":
        String(item.authentication||"NOT_VERIFIED")+
        " · V1 worker "+(item.v1_writer_active?"active":"unverified/offline")+
        " · account "+(item.account_verified?"verified":"not verified");
      section.textContent=titles[item.broker]+" · "+state+
        " · V2 live cutover: NOT READY · First blocker: "+
        String(item.first_blocker||"NOT_VERIFIED")+
        " · Orders: "+String(journal.state||"UNVERIFIED")+
        (journal.unresolved==null?"":" · Local unresolved: "+Number(journal.unresolved))+
        (item.broker==="webull"||item.broker==="robinhood_crypto"
          ?" · V1 local journal audit: "+String(local.state||"UNAVAILABLE")+
            (local.local_record_count==null?"":" · V1 records: "+Number(local.local_record_count))+
            (local.local_filled_count==null?"":" · Local filled records: "+Number(local.local_filled_count))+
            (local.incomplete_fill_details==null?"":" · Incomplete local fill evidence: "+Number(local.incomplete_fill_details))+
            " · Signed broker reconciliation: NOT VERIFIED"
          :"")+
        " · Market: "+String(item.source_state||"UNVERIFIED")+
        " · Session: "+String((item.market_session||{}).state||"NOT_VERIFIED")+
        " (broker hours not certified)" +
        " · V1 risk: "+String(risk.state||"UNVERIFIED")+
        (values?" · Saved limits: "+values:"")+
        " · Effective V1 risk budget preview: "+String(envelope.state||"NOT_VERIFIED")+
        (envelope.requested_order_ceiling_usd==null?"":" · Requested order ceiling $"+
          String(envelope.requested_order_ceiling_usd))+
        (envelope.preliminary_budget_usd==null?"":" · Preliminary permitted new-entry budget $"+
          String(envelope.preliminary_budget_usd))+
        (envelope.buying_power_preliminary_ceiling_usd==null?"":" · Buying-power-only ceiling $"+
          String(envelope.buying_power_preliminary_ceiling_usd))+
        " · Does NOT authorize any V2 order";
      cutover.append(section);
    }
  }
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
      showCutover(data.cutover_preflight);
      void readStockShadowStatus();
      void readFreshPaperStatus();
      void readRecordedReplay();
    }catch(_error){
      target.textContent="V2 status unavailable. V1 broker operation is unchanged.";
      if(health)health.textContent="Read-only broker adapter evidence unavailable.";
      if(cutover)cutover.textContent="V2 cutover preflight unavailable; no live-order authority.";
    }
  }

  const stockStatus=document.getElementById("v2-stock-shadow-status");
  const stockSymbols=document.getElementById("v2-stock-shadow-symbols");
  async function readStockShadowStatus(){
    if(!stockStatus)return;
    try{
      const response=await fetch("/api/v2/stock-shadow",{
        credentials:"same-origin",cache:"no-store",
        headers:{"Accept":"application/json"}});
      if(!response.ok)throw Error("Stock shadow worker status unavailable");
      const data=await response.json();
      const rows=Array.isArray(data.reports)?data.reports:[];
      const states={};
      for(const row of rows){
        const state=String(row.state||"UNKNOWN");
        states[state]=(states[state]||0)+1;
      }
      stockStatus.textContent="Schwab V2 stock shadow: "+
        String(data.state||"NOT_STARTED")+" · "+
        rows.length+"/"+Number(data.universe_size||24)+" monitored symbols · "+
        Object.entries(states).map(([key,value])=>key+" "+value).join(" · ")+
        " · Read-only signals recorded: "+Number(data.signals_recorded||0)+
        " · Live V2 orders: 0"+
        (data.heartbeat_age_sec!=null?
          " · Last heartbeat "+Number(data.heartbeat_age_sec)+"s ago":"");
      if(stockSymbols){
        stockSymbols.replaceChildren();
        for(const row of rows){
          if(!row||typeof row.symbol!=="string")continue;
          const line=document.createElement("p");
          const review=row.ai_shadow||{};
          line.textContent=row.symbol+" · "+String(row.state||"UNKNOWN")+
            " · "+Number(row.recorded_candle_count||0)+" genuine 5m bars"+
            (row.signal?" · "+row.signal+" read-only signal":"")+
            (row.reason?" · "+String(row.reason):"")+
            (row.last_closed_bar_at?" · Last bar "+String(row.last_closed_bar_at):"")+
            (review.state&&review.state!=="NOT_INVOKED"?
              " · AI shadow "+String(review.state)+
              (review.latency_ms==null?"":" · "+
                Number(review.latency_ms)+"ms"):"");
          stockSymbols.append(line);
        }
      }
    }catch(_error){
      stockStatus.textContent="V2 stock shadow status unavailable. Existing broker execution is unchanged.";
    }
  }

  const freshNode=document.getElementById("v2-paper-fresh-report");
  const activityNode=document.getElementById("v2-paper-activity-report");
  const economicsNode=document.getElementById("v2-paper-econ-report");
  function showPaperEconomics(data){
    if(!economicsNode)return;
    economicsNode.replaceChildren();
    const summary=document.createElement("p");
    summary.className="muted";
    summary.textContent="Cumulative isolated simulator results only; not live broker P/L. Estimated spread/slippage cannot be separately verified.";
    economicsNode.append(summary);
    const results=data&&data.economic_reconciliation&&
      typeof data.economic_reconciliation==="object"?data.economic_reconciliation:{};
    for(const symbol of ["BTCUSD","ETHUSD"]){
      const card=results[symbol];
      if(!card || card.simulated_only!==true || card.live_orders_authorized!==false)continue;
      const item=document.createElement("p");
      if(card.state!=="SIMULATED_CASH_AND_POSITIONS_RECONCILED" ||
         card.cash_reconciled!==true){
        item.textContent=symbol+" · Simulated economics unavailable — "+
          String(card.state||"LEDGER_UNVERIFIED")+
          " · No performance claim";
      }else{
        item.textContent=symbol+
          " · "+Number(card.simulated_fills||0)+" confirmed simulated fills"+
          " · "+Number(card.completed_round_trips||0)+" closed round trips"+
          " · "+Number(card.winning_round_trips||0)+" profitable"+
          " · Assumed fees $"+String(card.total_assumed_fees_usd)+
          " · Realized net after fees $"+String(card.realized_net_pnl_usd)+
          " · Remaining simulated qty "+String(card.remaining_quantity)+
          " · Wallet cash / holdings reconciled";
      }
      economicsNode.append(item);
    }
  }
  function showPaperActivity(data){
    if(!activityNode)return;
    activityNode.replaceChildren();
    const note=document.createElement("p");
    note.className="muted";
    note.textContent="Real recorded scan-minutes and verified *simulated* fills; 3h window does not claim net trading profits. No V2 broker order authority.";
    activityNode.append(note);
    for(const [key,title] of [["activity_3h","Last 3 hours"],["activity_24h","Last 24 hours"]]){
      const windowData=data&&data[key]&&typeof data[key]==="object"?data[key]:{};
      for(const symbol of ["BTCUSD","ETHUSD"]){
        const card=windowData[symbol];
        if(!card || card.live_orders_authorized!==false)continue;
        const reasons=card.rejection_reasons&&typeof card.rejection_reasons==="object"?
          Object.entries(card.rejection_reasons).sort((a,b)=>Number(b[1])-Number(a[1])).slice(0,4):[];
        const line=document.createElement("p");
        line.textContent=title+" · "+symbol+" · "+
          Number(card.scan_minutes||0)+" observed scan-minutes · "+
          Number(card.signal_minutes||0)+" signal-minutes · "+
          Number(card.entry_blocked_minutes||0)+" entry-blocked · "+
          Number(card.exit_blocked_minutes||0)+" exit-blocked · "+
          (card.fills_state==="SIMULATED_LEDGER_VERIFIED"?
            Number(card.simulated_fills)+" verified simulated fills ("+
            Number(card.simulated_buys)+" buys / "+Number(card.simulated_sells)+
            " sells, assumed fees $"+String(card.simulated_fee_usd)+")":
            "Simulated fills unavailable — "+String(card.fills_state||"unverified"))+
          (reasons.length?" · Why no trade: "+reasons.map(([reason,count])=>
             String(reason)+" "+Number(count)).join(", "):"")+
          " · AI PASS/VETO/UNAVAILABLE "+
          Number((card.ai_shadow||{}).PASS||0)+"/"+
          Number((card.ai_shadow||{}).VETO||0)+"/"+
          Number((card.ai_shadow||{}).UNAVAILABLE||0)+
          " · Fee/reward shadow: "+
          (card.fee_shadow_coverage==="OBSERVED_ADVISORY_ONLY"?
             ("past-high room "+Number((card.fee_shadow||{}).SHADOW_PASS_PAST_RESISTANCE_ROOM||0)+
              ", insufficient net upside "+Number((card.fee_shadow||{}).SHADOW_REJECT_REWARD_AFTER_FEES||0)+
              ", spread rejects "+Number((card.fee_shadow||{}).SHADOW_REJECT_SPREAD||0)+
              ", missing evidence "+Number((card.fee_shadow||{}).INSUFFICIENT_HISTORY||0)+
              " (advisory only)"):"not yet recorded")+
          " · Market data errors "+Number(card.data_error_minutes||0);
        activityNode.append(line);
      }
    }
  }
  async function readFreshPaperStatus(){
    if(!freshNode)return;
    try{
      const response=await fetch("/api/v2/paper-fresh",{
        credentials:"same-origin",cache:"no-store",
        headers:{"Accept":"application/json"}});
      if(!response.ok)throw Error("Fresh-paper worker status unavailable");
      const data=await response.json();
      showPaperActivity(data);
      showPaperEconomics(data);
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
        if(report.ai_shadow && typeof report.ai_shadow==="object"){
          const review=report.ai_shadow;
          text+=" · AI shadow: "+String(review.state||"UNAVAILABLE");
          if(review.model)text+=" ("+String(review.model)+")";
          if(review.latency_ms!==undefined)
            text+=" · "+Number(review.latency_ms)+"ms";
          if(review.reason)text+=" — "+String(review.reason);
          text+=" · AI has no order authority";
        }
        const fee=report.fee_shadow||{};
        if(fee.state && fee.state!=="NOT_INVOKED" &&
           fee.changed_execution===false && fee.live_order_authorized===false){
          text+=" · Fee/reward shadow "+String(fee.state);
          if(fee.hypothetical_net_at_prior_high_pct!==undefined)
            text+=" · Hypothetical net at prior resistance "+
               String(fee.hypothetical_net_at_prior_high_pct)+"%";
          text+=" · Advisory only (no trade veto, not a forecast)";
        }
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
      const cards=(data.scorecards&&typeof data.scorecards==="object")?
        data.scorecards:{};
      for(const symbol of ["BTCUSD","ETHUSD"]){
        const card=cards[symbol];
        if(!card||card.state!=="OBSERVED")continue;
        const summary=document.createElement("p");
        summary.className="muted";
        const ai=card.ai_shadow||{};
        summary.textContent=symbol+" · 24h paper scan history: "+
          Number(card.sample_minutes||0)+" observed minutes · "+
          Number(card.no_signal_minutes||0)+" NO_SIGNAL · "+
          Number(card.signal_minutes||0)+" qualified signals · "+
          Number(card.fill_minutes||0)+" simulated-fill minutes · "+
          Number(card.data_error_minutes||0)+" data errors · "+
          "AI shadow PASS/VETO/UNAVAILABLE "+
          Number(ai.PASS||0)+"/"+Number(ai.VETO||0)+"/"+
          Number(ai.UNAVAILABLE||0)+
          " · Paper-only marked P/L $"+
          (card.synthetic_pnl_usd==null?"unavailable":String(card.synthetic_pnl_usd))+
          " · Peak-to-trough paper drawdown "+
          (card.max_paper_drawdown_pct==null?"unavailable":
             String(card.max_paper_drawdown_pct)+"%");
        freshNode.append(summary);
      }
      if(freshNode.childElementCount===0)
        freshNode.textContent="No verified V2 paper worker observations yet.";
    }catch(_error){
      freshNode.textContent="Fresh-paper worker status unavailable. No live orders are affected.";
      if(activityNode)activityNode.textContent="Rolling paper activity unavailable; scan records and simulated fill counts could not be verified.";
      if(economicsNode)economicsNode.textContent="Simulated economic reconciliation unavailable; no performance claim can be made.";
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
