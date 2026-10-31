"use strict";
const paperResearchEscape=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
async function refreshPaperResearch(){
 const data=await request("/api/paper-lab");
 for(const key of ["equity","crypto"]){
  const a=data.accounts[key];
  const accuracy=a.accuracy===null?"Not measured":(100*a.accuracy).toFixed(1)+"%";
  document.getElementById("paper-research-"+key).textContent=
   "Recorded "+a.predictions+" | Scored "+a.settled+" | Accuracy "+accuracy+
   " | Research-only long evaluation $"+a.paper_net.toFixed(2);
 }
 document.getElementById("paper-research-schedule").textContent=
  data.schedule?.enabled?"Disable hourly research":"Enable hourly research";
 document.getElementById("paper-research-rows").innerHTML=(data.records||[]).map(r=>
  "<tr><td>"+paperResearchEscape(r.symbol)+"</td><td>"+paperResearchEscape(r.market)+
  "</td><td>"+paperResearchEscape(r.direction)+"</td><td>"+Number(r.hours)+"</td><td>"+
  (r.outcome?(r.outcome.correct?"Correct":"Incorrect"):"Pending")+
  "</td><td>"+paperResearchEscape(r.reason)+"</td></tr>").join("")||
  '<tr><td colspan="6">No recorded forecasts.</td></tr>';
}
document.addEventListener("DOMContentLoaded",()=>{
 const run=document.getElementById("paper-research-run");
 const schedule=document.getElementById("paper-research-schedule");
 const message=document.getElementById("paper-research-message");
 if(!run||!schedule)return;
 run.addEventListener("click",async()=>{
  run.disabled=true;message.textContent="Evaluating the public markets and AI model...";
  try{
   const d=await request("/api/paper-lab/run",{method:"POST",body:"{}"});
   message.textContent="New: "+d.added.join(", ")+"; resolved: "+d.settled+
    "; unavailable: "+Object.keys(d.errors||{}).join(", ");
   await refreshPaperResearch();
  }catch(e){message.textContent=e.message}finally{run.disabled=false}
 });
 schedule.addEventListener("click",async()=>{
  try{
   const current=await request("/api/paper-lab");
   const enabled=!current.schedule.enabled;
   await request("/api/paper-lab/schedule",{method:"POST",body:JSON.stringify({enabled})});
   message.textContent=enabled?"Hourly research on":"Hourly research off";
   await refreshPaperResearch();
  }catch(e){message.textContent=e.message}
 });
});
