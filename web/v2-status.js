"use strict";
// Read-only V2 foundation status. Intentionally contains no trading controls.
document.addEventListener("DOMContentLoaded",()=>{
  const target=document.getElementById("v2-foundation-status");
  const health=document.getElementById("v2-adapter-health");
  if(!target)return;
  function showAdapters(rows,market){
    if(!health)return;
    health.replaceChildren();
    if(!Array.isArray(rows)||!rows.length){
      health.textContent="No verified read-only broker observations loaded.";return;
    }
    const display={schwab:"Schwab stocks",webull:"Webull stocks",
      robinhood_crypto:"Robinhood crypto",paper:"Paper trading"};
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
      const permission=row.permission_armed?"V1 armed":"V1 not armed";
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
        " · Market: "+quote+" (read-only)";
      line.append(body);
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
      const flag=data.feature_enabled?"Enabled for paper/replay":"Disabled by default";
      const store=data.store||"Unavailable";
      target.textContent="V2 "+String(data.version||"experimental")+
        " · "+flag+" · Live broker authority: OFF"+
        " · Event store: "+store+
        " · Persisted intents: "+Number(data.intents||0)+
        " · Unresolved: "+Number(data.unresolved||0);
      showAdapters(data.broker_adapters,data.market_sources);
    }catch(_error){
      target.textContent="V2 status unavailable. V1 broker operation is unchanged.";
      if(health)health.textContent="Read-only broker adapter evidence unavailable.";
    }
  }
  document.getElementById("v2-status-refresh")?.addEventListener("click",readV2Status);
  document.getElementById("operations-refresh")?.addEventListener("click",readV2Status);
  document.querySelector('[data-view="operations"]')?.addEventListener("click",readV2Status);
});
