"use strict";
// Read-only V2 foundation status. Intentionally contains no trading controls.
document.addEventListener("DOMContentLoaded",()=>{
  const target=document.getElementById("v2-foundation-status");
  if(!target)return;
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
    }catch(_error){target.textContent="V2 status unavailable. V1 broker operation is unchanged.";}
  }
  document.getElementById("v2-status-refresh")?.addEventListener("click",readV2Status);
  document.getElementById("operations-refresh")?.addEventListener("click",readV2Status);
  document.querySelector('[data-view="operations"]')?.addEventListener("click",readV2Status);
});
