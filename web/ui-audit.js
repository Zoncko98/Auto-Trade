"use strict";
/* Four-broker UI audit presentation layer. Read-only: never POSTs to broker/order/risk APIs. */
(function(){
 const $=id=>document.getElementById(id);
 const localZone="America/Phoenix";
 const unavailable="Not verified";
 const fields=["connection","scanner","permission","block","fill"];
 const labels=["Broker / environment","Scanner","Order permission","Order / risk block","Last verified fill"];
 const latest={live:null,robinhood:null,webull:null,paper:null};
 const auditRows={live:[],robinhood:[],webull:[],paper:[]};
 function stamp(value){
   if(!value)return {label:"Not reported",utc:""};
   const ms=Date.parse(value);
   if(!Number.isFinite(ms))return {label:"Not reported",utc:""};
   const d=new Date(ms);
   return {label:new Intl.DateTimeFormat("en-US",{
       timeZone:localZone,year:"numeric",month:"short",day:"numeric",
       hour:"numeric",minute:"2-digit",second:"2-digit",timeZoneName:"short"
     }).format(d),utc:d.toISOString()};
 }
 function ageFresh(value,ms=180000){
   const t=Date.parse(value||"");
   return Number.isFinite(t)&&Date.now()-t>=-60000&&Date.now()-t<=ms;
 }
 function mask(value){
   const s=String(value||"");
   if(!s)return "Unavailable";
   return "••••"+s.slice(-4);
 }
 function statusText(value){
   if(value===null||value===undefined||value==="")return "Not reported";
   const raw=String(value);
   const names={ARMED_NO_ORDER:"Armed; no qualifying order",
     TECHNICAL_ONLY_NEWS_OPTIONAL:"Technical-only news-optional review",
     ACCOUNT_PREFLIGHT_PASSED_SIGNAL_NOT_CHECKED:"Account preflight passed; signal pending",
     BLOCKED_OrderPassBlocked:"Order pass blocked",
     NO_SIGNAL:"No qualifying signal",
     NOT_INVOKED:"AI not invoked",
     RECONCILIATION_PENDING:"Reconciliation pending",
     SUBMITTED_UNCONFIRMED:"Submitted; fill unconfirmed",
     "MARKET_DATA_SIGNAL_BROKER_SPREAD_ABOVE_0.5":"Broker spread exceeds 0.5% entry ceiling",
     NOT_ARMED:"Worker did not authorize an order",
     NO_WORKER_REPORT:"No current worker report"};
   if(names[raw])return names[raw];
   const human=raw.replace(/_/g," ").replace(/([a-z])([A-Z])/g,"$1 $2").replace(/\s+/g," ").trim();
   if(/^[A-Z0-9_.-]+$/.test(raw)&&raw.includes("_"))return human.charAt(0)+human.slice(1).toLowerCase();
   return human;
 }
 function moneySigned(raw){
   if(raw===null||raw===undefined||raw==="")return "Unavailable";
   const n=Number(raw);
   if(!Number.isFinite(n))return "Unavailable";
   const formatted=new Intl.NumberFormat("en-US",{style:"currency",currency:"USD",
     minimumFractionDigits:2,maximumFractionDigits:Math.abs(n)<0.01&&n!==0?8:2}).format(Math.abs(n));
   return n>0?"▲ +"+formatted:n<0?"▼ −"+formatted:"— "+formatted;
 }
 function percentSigned(raw){
   if(raw===null||raw===undefined||raw==="")return "Unavailable";
   const n=Number(raw);if(!Number.isFinite(n))return "Unavailable";
   return (n>0?"▲ +":n<0?"▼ −":"— ")+Math.abs(n).toFixed(2)+"%";
 }
 function pnlClass(el,raw){
   if(!el)return;
   const n=Number(raw);
   el.classList.remove("pnl-up","pnl-down","pnl-flat");
   if(raw===null||raw===undefined||!Number.isFinite(n))return;
   el.classList.add(n>0?"pnl-up":n<0?"pnl-down":"pnl-flat");
   el.setAttribute("aria-label",(n>0?"Gain ":n<0?"Loss ":"No change ")+el.textContent);
 }
 function field(wrapper,key,value,state){
   const target=wrapper.querySelector('[data-status-field="'+key+'"]');
   if(!target)return;
   const v=typeof value==="string"&&value.trim()?value:"Not verified";
   target.textContent=v;
   target.dataset.state=state||"unknown";
 }
 function mountStatus(key,view){
   const container=$("view-"+view),hero=container?.querySelector(".hero-head");
   if(!container||!hero||$("audit-status-"+key))return;
   const card=document.createElement("section");
   card.id="audit-status-"+key;card.className="audit-status-strip";
   card.setAttribute("aria-label","Read-only account readiness, separated by verification gate");
   const title=document.createElement("div");
   title.className="audit-status-head";
   const strong=document.createElement("strong");
   strong.textContent="Account readiness · independent checks";
   const seen=document.createElement("span");
   seen.id="audit-observed-"+key;
   seen.textContent="Latest observation not yet verified";
   title.append(strong,seen);card.append(title);
   const grid=document.createElement("div");grid.className="audit-status-grid";
   fields.forEach((key2,i)=>{
     const box=document.createElement("div");box.className="audit-status-cell";
     const label=document.createElement("span");label.textContent=labels[i];
     const value=document.createElement("strong");
     value.dataset.statusField=key2;value.dataset.state="unknown";
     value.textContent="Checking…";box.append(label,value);grid.append(box);
   });
   card.append(grid);
   const note=document.createElement("p");
   note.className="audit-status-foot";
   note.textContent="A connected account or armed policy alone does not mean an order can be submitted, accepted or filled.";
   card.append(note);
   hero.after(card);
 }
 function setStatus(key,record){
   latest[key]=record;
   const node=$("audit-status-"+key);
   if(!node)return;
   fields.forEach(id=>field(node,id,record[id]?.text,record[id]?.state));
   const at=$("audit-observed-"+key);
   if(at)at.textContent=record.at?"Observed "+stamp(record.at).label:"Observation time unavailable";
   updateTile(key,record);
 }
 function updateTile(key,record){
   const id=key==="robinhood"?"robinhood_crypto":key==="live"?"live":key==="paper"?"paper":"webull";
   const tile=document.querySelector('[data-workspace="'+id+'"]');
   if(!tile)return;
   let el=tile.querySelector(".audit-tile-ready");
   if(!el){el=document.createElement("span");el.className="audit-tile-ready";
     const open=tile.querySelector(".workspace-tile-open");
     if(open)tile.insertBefore(el,open);else tile.append(el);}
   const parts=[
     record.connection?.text||"Not verified",
     record.permission?.text||"Not verified",
     record.block?.text||"Block unverified"
   ];
   el.textContent=parts.join(" · ");
   el.title="Connection and order permissions are independent. See account for source and time.";
 }
 function fillFromOrders(rows){
   if(!Array.isArray(rows))return "Not reported";
   const matched=rows.filter(o=>o?.state==="FILLED" &&
     o.filled_price!==null&&o.filled_price!==undefined);
   if(!matched.length)return "No broker-confirmed fill in worker journal";
   const sorted=matched.slice().sort((a,b)=>
     (Date.parse(b.fill_at||b.filled_at||b.created_at||"")||0)-
     (Date.parse(a.fill_at||a.filled_at||a.created_at||"")||0));
   const row=sorted[0];
   const at=row.fill_at||row.filled_at||row.executed_at||"";
   return "Broker-confirmed: "+(row.symbol||"asset")+
      (at?" · "+stamp(at).label:" · time not recorded");
 }
 function live(data){
   const fresh=data?.worker_online===true&&
     Number.isFinite(Number(data?.heartbeat_age_sec))&&
     Number(data.heartbeat_age_sec)>=0&&Number(data.heartbeat_age_sec)<=120&&
     ageFresh(data?.account?.at,300000);
   const halted=data?.journal_halted===true;
   const armed=data?.armed===true&&data?.worker_online===true;
   const running=armed&&data?.order_permission==="running";
   const count=Array.isArray(data?.orders)?data.orders.length:null;
   const locked=Array.isArray(data?.orders)?
     data.orders.some(o=>!["FILLED","REJECTED","CANCELED","EXPIRED"].includes(o?.state)):true;
   setStatus("live",{
     at:data?.account?.at||"",
     connection:{text:fresh?"Broker snapshot current":"Broker snapshot stale/unverified",state:fresh?"good":"bad"},
     scanner:{text:data?.worker_online?"Worker reporting; last scan requires decision evidence":"Not reporting",state:data?.worker_online?"good":"bad"},
     permission:{text:running?"Running (cash only)":halted?"Halted":armed?"Paused":"Not armed",state:running?"good":"warn"},
     block:{text:halted?"Reconciliation halt":locked?"Unresolved order state — review":"No unresolved journal orders; other gates apply",state:halted||locked?"bad":"warn"},
     fill:{text:fillFromOrders(data?.orders),state:"neutral"}});
   const summary=$("audit-live-order-summary");
   if(summary)summary.textContent=(count===null?"Journal unavailable":count+" worker order records")+
     " · "+(locked?"Unresolved record requires review":"No unresolved order state reported")+
     " · Broker state is not inferred from submission.";
   const table=$("audit-live-order-rows");
   if(table){
     const source=$("live-orders-table");
     if(!source||!source.rows.length){
       table.innerHTML='<tr><td colspan="9">No broker orders recorded.</td></tr>';
     }else{
       table.replaceChildren();
       Array.from(source.rows).forEach(original=>{
         const copy=original.cloneNode(true);
         if(copy.cells.length===10)copy.deleteCell(9);
         table.append(copy);
       });
     }
   }
   audit("live",(Array.isArray(data?.decisions)?data.decisions:[]).map(e=>({
     at:e.at,asset:e.symbol,stage:/AI|VETO/i.test(e.decision||"")?"Model / news":
       e.decision==="NO_SIGNAL"?"Technical signal":
       e.decision==="ORDER_INTENT"?"Order intent":"Strategy / risk",
     result:e.decision||"Unknown",reason:e.summary||"No recorded reason",
     model:e.model||"",invoked:!!e.model&&e.model!=="rule-based",
     sourceAge:e.headlines?.length?"Headlines saved; publication dates in expanded evidence":"Not recorded",
     order:e.decision==="ORDER_INTENT"?"Intent recorded; broker acceptance not implied":"No order inferred",
     raw:e})));
   const pnl=$("schwab-perf-pnl"),ret=$("schwab-perf-return");
   if(pnl&&pnl.textContent!=="Unavailable"){
     const num=parseMoney(pnl.textContent);
     if(num!==null){pnl.textContent=moneySigned(num);pnlClass(pnl,num);}
   }
   if(ret&&ret.textContent!=="Unavailable"){
     const num=parseFloat(ret.textContent);
     if(Number.isFinite(num)){ret.textContent=percentSigned(num);pnlClass(ret,num);}
   }
 }
 function parseMoney(v){const t=String(v||"").replace(/[$, ▲▼+−]/g,"").trim();
   const n=Number(t);return t&&Number.isFinite(n)?n:null;}
 function robinhood(result,effective){
   const worker=result?.worker||{},accounts=Array.isArray(result?.accounts)?result.accounts:[];
   const connected=result?.connected===true&&accounts.some(a=>a.status==="active");
   const at=worker.updated_at||"";
   const fresh=ageFresh(at,180000);
   const pending=Array.isArray(result?.pending_orders)?result.pending_orders:null;
   const unresolved=Number.isInteger(worker.pending_order_intents)?worker.pending_order_intents:pending?.length;
   const blocked=String(worker.execution_status||"").startsWith("BLOCKED")||
     (Number.isInteger(unresolved)&&unresolved>0);
   const reason=String(worker.execution_reason||worker.risk_check||"").slice(0,180);
   setStatus("robinhood",{
     at,
     connection:{text:connected?"Authenticated Crypto account":"Broker account unverified",state:connected?"good":"bad"},
     scanner:{text:fresh?"Scanner reporting · "+(worker.quotes_checked??"—")+" quotes":"Scanner stale or unverified",state:fresh?"good":"bad"},
     permission:{text:effective?.armed?"Policy armed; other gates apply":"Not armed / restricted",state:effective?.armed?"warn":"bad"},
     block:{text:blocked?"Order/risk block · "+statusText(reason||worker.execution_status):
       "No open intent reported; signal and risk still required",state:blocked?"bad":"warn"},
     fill:{text:worker.last_order_confirmed===true?
       "Bot fill reported; see order evidence (time unavailable)":
       "No confirmed autonomous fill reported",state:"neutral"}});
   const orderSummary=$("audit-robinhood-orders");
   if(orderSummary){
     orderSummary.replaceChildren();
     const entries=[
       ["Unresolved bot intents",Number.isInteger(unresolved)?unresolved:"Unavailable"],
       ["Order permission",effective?.armed?"Armed policy; signal and checks pending":"Disarmed or restricted"],
       ["Worker execution",statusText(worker.execution_status||"Not reported")],
       ["Last confirmed bot fill",worker.last_order_confirmed===true?
         "Reported; timestamp not available":"Not reported"],
       ["Order block",blocked?statusText(reason||worker.execution_status):"No unresolved intent reported"]
     ];
     const status=document.createElement("div");status.className="audit-order-fields";
     entries.forEach(([label,value])=>{
       const p=document.createElement("p"),a=document.createElement("span"),b=document.createElement("strong");
       a.textContent=label;b.textContent=String(value);p.append(a,b);status.append(p);
     });orderSummary.append(status);
     const list=document.createElement("div");list.className="audit-pending-orders";
     if(pending?.length){
       pending.forEach(x=>{
         const row=document.createElement("p");
         row.textContent=(x.symbol||"Unknown")+" "+(x.side||"")+
           " · local "+statusText(x.local_status)+
           " · broker "+(x.broker_matched?statusText(x.broker_state):"not matched")+
           " · last checked "+(x.checked_at?stamp(x.checked_at).label:"not reported");
         list.append(row);
       });
     }else list.textContent="No current unresolved bot order list reported.";
     orderSummary.append(list);
   }
   const count=$("robinhood-orders-stat");
   if(count)count.textContent=Number.isInteger(unresolved)?String(unresolved):"Unavailable";
   const countNote=$("rh-bot-order-note");
   if(countNote)countNote.textContent=Number.isInteger(unresolved)?
     "Unresolved bot intents; broker historical orders are separate":
     "Bot order reconciliation unavailable; broker history is not a bot count";
 }
 function robinhoodPortfolio(result){
   const history=$("audit-robinhood-history");
   if(history)history.textContent=Number.isInteger(result?.order_count)?
     "Robinhood historical broker orders: "+result.order_count+
       ". This does not establish Auto Trader submission, acceptance or fill.":
     "Robinhood broker historical order count unavailable; bot fills are not inferred.";
 }
 function webullAccount(data){
   latest.webullConnection=data;
 }
 function webullTrader(data,workerFresh,armed){
   const worker=data?.worker||{},policy=data?.policy||{};
   const accounts=Array.isArray(latest.webullConnection?.accounts)?latest.webullConnection.accounts:[];
   const connected=latest.webullConnection?.connected===true&&accounts.some(a=>!!a.account_id);
   const waiting=Array.isArray(worker.pending_orders)?worker.pending_orders.length:null;
   const source=data.execution_validated===true;
   const blocked=String(worker.execution_status||"").startsWith("BLOCKED")||
     (waiting!==null&&waiting>0);
   const names=Array.isArray(data.orders)?data.orders:[];
   const filled=names.filter(x=>x.status==="FILLED"&&x.filled_price!=null);
   const last=filled.sort((a,b)=>(Date.parse(b.fill_at||"")||0)-(Date.parse(a.fill_at||"")||0))[0];
   setStatus("webull",{
     at:worker.updated_at||"",
     connection:{text:connected?"Authenticated Webull account":"Account verification unavailable",state:connected?"good":"bad"},
     scanner:{text:workerFresh?"Scanner reporting":"Scanner stale/unverified",state:workerFresh?"good":"bad"},
     permission:{text:armed?"Armed policy; broker gates apply":policy.enabled?"Saved policy armed; worker unverified":"Disarmed",state:armed?"warn":"bad"},
     block:{text:blocked?"Order/risk block: "+statusText(worker.execution_reason||worker.execution_status):
       "No unresolved bot orders reported; broker checks remain mandatory",state:blocked?"bad":"warn"},
     fill:{text:last?"Broker-confirmed "+(last.symbol||"order")+" · "+
       stamp(last.fill_at).label:source?"Lifecycle verified; no filled bot order reported":
       "No independently verified bot fill",state:"neutral"}});
   const count=$("webull-orders-count");
   if(count)count.textContent=Array.isArray(data.orders)?String(names.length):"Unavailable";
   const note=$("webull-bot-order-note");
   if(note)note.textContent="Worker order intents · pending "+
     (waiting===null?"unknown":waiting)+"; not broker historical count";
   compactWebullDiagnostics();
 }
 function webullPolicy(data){
   const p=data?.policy||{},state=$("webull-risk-current-policy");
   if(state)state.textContent="Current saved policy: "+(p.enabled===true?"armed":"disarmed")+
     " · broker order lifecycle "+(data.execution_validated===true?"verified":"not independently verified");
   const preview=$("webull-risk-permission-preview");
   if(preview)preview.textContent=p.enabled===true?"Armed; broker checks required":"Disarmed";
   webullRisk();
 }
 function paper(data){
   const runtime=data?.runtime||{},control=data?.control||{};
   const mode=control.mode||"unknown";
   const online=runtime.online===true;
   const reason=runtime.last_paper_reason||runtime.last_paper_decision||"";
   setStatus("paper",{
     at:runtime.paper_feed_checked_at||runtime.last_scan_at||"",
     connection:{text:"Simulator · no real brokerage connection",state:"neutral"},
     scanner:{text:online&&mode==="running"?"Simulated scanner running":online?"Monitor reporting · "+statusText(mode):"Monitor not reporting",state:online?"good":"bad"},
     permission:{text:"Virtual funds only · "+statusText(mode),state:"neutral"},
     block:{text:reason?statusText(reason.slice(0,170)):"No recent decision reason",state:"warn"},
     fill:{text:"No real broker fills; simulation history only",state:"neutral"}});
   const empty=$("equity-chart");
   if(empty?.classList.contains("empty-history"))
     empty.title="Insufficient recorded equity snapshots; trades can exist without a historical curve.";
 }
 function parseFields(str){
   const src=String(str||"").trim();
   if(!src)return {summary:"No diagnostics reported",raw:""};
   const parts=src.split(/\s+\|\s+/);
   const useful=parts.filter(x=>!/\bNO_SIGNAL\b/.test(x)).slice(0,2);
   return {summary:parts.length+" symbol checks; "+(useful.length?useful.join(" · "):
     "no qualifying signal in the current scan"),raw:src};
 }
 function compactRobinhoodDiagnostics(node,worker){
   if(!node)return;
   const input=worker?.signal_diagnostics||"";
   const parsed=parseFields(input);
   node.replaceChildren();
   const summary=document.createElement("span");summary.textContent=parsed.summary;
   node.append(summary);
   if(parsed.raw){
     const details=document.createElement("details");details.className="audit-inline-details";
     const title=document.createElement("summary");title.textContent="All per-symbol technical checks";
     const raw=document.createElement("p");raw.textContent=parsed.raw;raw.className="audit-raw";
     details.append(title,raw);node.append(details);
   }
 }
 function compactWebullDiagnostics(){
   const container=$("webull-engine-fields");
   if(!container)return;
   const rows=Array.from(container.children);
   const keep=["Scanner","Last order decision","AI approvals","Market symbols checked",
     "Webull orders unresolved","Trading permission","Webull broker lifecycle validation",
     "Last block","Crypto execution"];
   const detail=document.createElement("details");detail.className="audit-inline-details audit-webull-details";
   const summary=document.createElement("summary");summary.textContent="Detailed feed, quota and account diagnostics";
   detail.append(summary);
   rows.forEach(node=>{
     if(node.tagName==="DETAILS")return;
     const text=node.textContent||"";
     if(!keep.some(label=>text.startsWith(label)))detail.append(node);
     else{
       const v=node.querySelector("strong");
       if(v)v.textContent=statusText(v.textContent);
     }
   });
   if(detail.children.length>1)container.append(detail);
 }
 function roRisk(){
   const read=id=>$(id)?.value?.trim()?Number($(id).value):NaN;
   const buying=parseMoney($("robinhood-cash-stat")?.textContent);
   const max=read("robinhood-risk-max"),exposure=read("robinhood-risk-exposure");
   const maxNode=$("rh-risk-max-preview"),exposureNode=$("rh-risk-exposure-preview");
   if(maxNode)maxNode.textContent=Number.isFinite(max)?"$"+max.toFixed(2):"Unavailable";
   if(exposureNode)exposureNode.textContent=Number.isFinite(exposure)?"$"+exposure.toFixed(2):"Unavailable";
   const cashNode=$("rh-risk-cash-preview");
   if(cashNode)cashNode.textContent=buying===null?"Unavailable":new Intl.NumberFormat("en-US",{style:"currency",currency:"USD"}).format(buying);
   const slots=$("rh-risk-positions-preview");
   if(slots)slots.textContent=$( "robinhood-risk-positions")?.value||"Unavailable";
   const permission=$("rh-risk-permission-preview");
   if(permission){
     const form=$("robinhood-risk-form");
     const selected=$("robinhood-risk-activate")?.checked===true;
     const saved=form?.dataset.savedPolicyEnabled;
     permission.textContent=saved===undefined?"Current saved policy unavailable":
       selected!== (saved==="true")?"Unsaved permission selection":
       saved==="true"?"Saved policy armed; all broker checks required":"Saved policy disarmed";
   }
   const result=$("robinhood-risk-preview");
   if(result)result.textContent=buying===null||!Number.isFinite(max)||!Number.isFinite(exposure)?"Unavailable":
     new Intl.NumberFormat("en-US",{style:"currency",currency:"USD"}).format(
       Math.max(0,Math.min(max,exposure,buying*.25)));
 }
 function webullRisk(){
   const read=id=>$(id)?.value?.trim()?Number($(id).value):NaN;
   const cap=read("webull-risk-order"),loss=read("webull-risk-loss"),pos=read("webull-risk-position");
   const pv=$("webull-risk-preview");
   if(pv)pv.textContent=Number.isFinite(cap)&&cap>=0?
     new Intl.NumberFormat("en-US",{style:"currency",currency:"USD"}).format(Math.min(cap,1000)):"Unavailable";
   const p=$("webull-risk-cap-preview");
   if(p)p.textContent=Number.isFinite(pos)?pos+"%":"Unavailable";
   const l=$("webull-risk-loss-preview");
   if(l)l.textContent=Number.isFinite(loss)?"$"+loss.toFixed(2):"Unavailable";
   const n=$("webull-risk-positions-preview");
   if(n)n.textContent=$("webull-risk-positions")?.value||"Unavailable";
 }
 function audit(kind,rows){
   auditRows[kind]=rows;
   drawAudit(kind);
 }
 function drawAudit(kind){
   const body=$("audit-table-"+kind);
   if(!body)return;
   const query=String($("audit-search-"+kind)?.value||"").toLowerCase();
   const stage=$("audit-stage-"+kind)?.value||"all";
   const archive=$("audit-archive-"+kind)?.value||"all";
   body.replaceChildren();
   const matched=(auditRows[kind]||[]).filter(r=>
     (stage==="all"||r.stage===stage)&&
     (archive==="all"||(archive==="legacy"?r.legacy===true:r.legacy!==true))&&
     [r.asset,r.stage,r.result,r.reason,r.model].some(v=>String(v||"").toLowerCase().includes(query)));
   matched.slice(0,80).forEach(r=>{
     const tr=document.createElement("tr");
     const date=stamp(r.at);
     const model=r.invoked===true?(r.model||"Model not recorded"):
       r.invoked===false?"AI not invoked":"Invocation unverified";
     const values=[date.label,r.asset||"Unavailable",r.stage||"Unclassified",
       statusText(r.result||"Not recorded"),statusText(r.reason||"No recorded rationale").slice(0,220),
       model,r.sourceAge||"Not recorded",r.order||"No order evidence"];
     values.forEach((value,i)=>{
       const cell=document.createElement("td");cell.textContent=value;
       if(i===0&&date.utc)cell.title="Full UTC: "+date.utc;
       if(i===5&&r.model&&!r.invoked)cell.title="Raw model-attribution field: "+r.model;
       tr.append(cell);
     });
     const extra=document.createElement("td");
     const det=document.createElement("details");
     const sum=document.createElement("summary");sum.textContent="Original evidence";
     const pre=document.createElement("pre");pre.className="audit-raw";
     pre.textContent=JSON.stringify(r.raw||{},null,2);
     det.append(sum,pre);extra.append(det);tr.append(extra);body.append(tr);
   });
   if(!matched.length){
     const tr=document.createElement("tr"),td=document.createElement("td");td.colSpan=9;
     td.textContent="No recorded events match these filters; this does not prove no broker activity.";
     tr.append(td);body.append(tr);
   }
   const count=$("audit-count-"+kind);
   if(count)count.textContent=matched.length+" matching records"+
     (matched.length>80?" · showing newest 80":"");
 }
 function robinhoodEvidence(data){
   const rows=Array.isArray(data?.decision_evidence)?data.decision_evidence:[];
   audit("robinhood",rows.slice().reverse().map(e=>{
     const status=String(e.ai_review_status||"");
     const tech=/NOT_INVOKED|TECHNICAL_ONLY/i.test(status);
     return {at:e.at,asset:e.entry_candidate_symbol||e.exit_candidate_symbol||e.signal||"",
       stage:e.execution_status&&e.execution_status!=="NO_ORDER"?"Order / risk":
         tech?"Technical signal":"Model / news",
       result:e.execution_status||e.ai_review_status||"Unclassified",
       reason:e.execution_reason||e.ai_reason||"No saved reason",
       model:e.ai_model||"",invoked:tech?false:e.ai_model?true:null,
       sourceAge:"Not recorded in this row",
       order:e.execution_status||"Not reported",
       raw:e};
   }));
 }
 function webullEvidence(items){
   const rows=[];
   (Array.isArray(items)?items:[]).forEach(item=>{
     const signals=Array.isArray(item.signals)?item.signals:[];
     signals.forEach(s=>rows.push({
       at:item.updated_at,asset:s.symbol,stage:"Technical signal",
       result:s.technical_approved?"Technical candidate":"No qualifying signal",
       reason:s.reason||"No saved reason",model:"",invoked:false,
       sourceAge:s.quote_age_seconds!=null?s.quote_age_seconds+" seconds":"Not recorded",
       order:"No broker order implied",raw:s}));
     (Array.isArray(item.ai_reviews)?item.ai_reviews:[]).forEach(a=>rows.push({
       at:item.updated_at,asset:a.symbol,stage:"Model / news",
       result:a.approved?"Approved in record":"Rejected in record",
       reason:a.reason||"No saved rationale",model:a.model||"",
       invoked:a.model?true:null,sourceAge:"Not recorded",
       order:"Broker order status independent",raw:a}));
     if(!signals.length && (!Array.isArray(item.ai_reviews)||item.ai_reviews.length===0))
       rows.push({at:item.updated_at,asset:"—",stage:"Strategy / risk",
         result:item.execution_status,reason:item.execution_reason,
         invoked:null,sourceAge:"Not recorded",order:"Not verified",raw:item});
   });
   audit("webull",rows);
   const root=$("webull-evidence-list");
   if(root&&root.parentElement?.tagName!=="DETAILS"){
     const detail=document.createElement("details");detail.className="audit-inline-details audit-full-history";
     const summary=document.createElement("summary");summary.textContent="Full Webull scanner rows";
     root.before(detail);detail.append(summary,root);
   }
 }
 function paperEvidence(items){
   audit("paper",(Array.isArray(items)?items:[]).map(r=>{
     const rawModel=r.model||"";
     const generic=!rawModel||rawModel==="shared_strategy"||rawModel==="rule-based";
     return {at:r.timestamp,asset:r.symbol,stage:/AI|news|veto/i.test(r.reason||"")?"Model / news":"Strategy / risk",
       result:r.approved?"Approved":"Rejected",reason:r.reason||"Rationale unavailable",
       model:rawModel,invoked:generic?null:true,
       sourceAge:"Not recorded",order:"Paper simulation; no broker order",
       legacy:generic,raw:r};
   }));
 }
 function paperTradeRationale(trade){
   if(trade?.reason==="Shared engine strategy decision")
     return "Recorded generic strategy rationale; specific signal/model evidence was not linked to this legacy trade";
   return trade?.reason||"No recorded trade rationale";
 }
 function decorateTimeCell(cell){
   if(!cell||cell.dataset.auditTimeStyled)return;
   const original=cell.textContent?.trim();
   if(!original||!Number.isFinite(Date.parse(original)))return;
   const at=stamp(original);
   if(!at.utc)return;
   cell.title="Full UTC: "+at.utc;
   cell.textContent=at.label;cell.dataset.auditTimeStyled="true";
 }
 function decorateTable(id){
   const table=$(id);
   if(!table)return;
   table.querySelectorAll("tr td:first-child").forEach(decorateTimeCell);
 }
 function ensureEvidence(kind,view,selectors){
   const container=$("view-"+view);
   if(!container)return;
   const panel=document.createElement("section");panel.className="panel audit-unified";
   const h=document.createElement("h2");h.textContent="Unified decision timeline";
   const p=document.createElement("p");p.className="panel-note";
   p.textContent="Search read-only evidence by asset, stage or result. Missing model invocation, sources and order confirmation remain explicitly unknown.";
   const filters=document.createElement("div");filters.className="audit-filters";
   const input=document.createElement("input");input.type="search";input.id="audit-search-"+kind;
   input.placeholder="Search asset, reason or result";input.setAttribute("aria-label","Search "+kind+" evidence");
   const select=document.createElement("select");select.id="audit-stage-"+kind;
   select.setAttribute("aria-label","Filter evidence by stage");
   ["all","Technical signal","Model / news","Strategy / risk","Order / risk","Order intent"].forEach(v=>{
     const option=new Option(v==="all"?"All stages":v,v);select.add(option);
   });
   filters.append(input,select);
   if(kind==="paper"){
     const archive=document.createElement("select");archive.id="audit-archive-paper";
     archive.setAttribute("aria-label","Filter model attribution");
     [["all","All records"],["legacy","Legacy / unverified attribution"],
      ["current","Recorded model attribution"]].forEach(([v,txt])=>archive.add(new Option(txt,v)));
     filters.append(archive);
     archive.addEventListener("change",()=>drawAudit(kind));
   }
   const count=document.createElement("p");count.id="audit-count-"+kind;count.className="panel-note";
   const scroll=document.createElement("div");scroll.className="table-wrap";
   const table=document.createElement("table");table.className="audit-table";
   const thead=document.createElement("thead"),head=document.createElement("tr");
   ["Observed (Arizona)","Asset","Stage","Result","Recorded reason","AI invocation","Source age","Order state","Details"].forEach(txt=>{
     const th=document.createElement("th");th.textContent=txt;head.append(th);});
   thead.append(head);
   const tbody=document.createElement("tbody");tbody.id="audit-table-"+kind;
   table.append(thead,tbody);scroll.append(table);
   panel.append(h,p,filters,count,scroll);
   const first=container.querySelector(selectors);
   if(first)first.before(panel);else container.append(panel);
   input.addEventListener("input",()=>drawAudit(kind));
   select.addEventListener("change",()=>drawAudit(kind));
   drawAudit(kind);
 }
 function collapseRawPanel(view,selector,label){
   const container=$("view-"+view),panel=container?.querySelector(selector);
   if(!panel||panel.parentElement?.tagName==="DETAILS")return;
   const wrapper=document.createElement("details");wrapper.className="audit-inline-details audit-full-history";
   const summary=document.createElement("summary");summary.textContent=label;
   panel.before(wrapper);wrapper.append(summary,panel);
 }
 function mount(){
   mountStatus("live","live");mountStatus("robinhood","robinhood");
   mountStatus("webull","webull");mountStatus("paper","overview");
   [["live","decisions",".list-panel"],["robinhood","robinhood-decisions",".list-panel"],
    ["webull","webull-decisions",".panel"],["paper","reviews",".list-panel"]]
    .forEach(([kind,view,selector])=>ensureEvidence(kind,view,selector));
   collapseRawPanel("decisions",".list-panel","Full Schwab decision audit with export and sources");
   collapseRawPanel("robinhood-decisions",".list-panel:last-child","Full Robinhood decision history and raw evidence");
   collapseRawPanel("reviews",".list-panel","Full paper evaluation history");
   const riskR=$("robinhood-risk-form");
   riskR?.addEventListener("input",roRisk);
   const riskW=$("webull-risk-form");
   riskW?.addEventListener("input",webullRisk);
   // Long order history remains accessible under a disclosure on overview.
   const journal=$("view-live")?.querySelector(".list-panel");
   if(journal && journal.parentElement?.tagName!=="DETAILS"){
     const details=document.createElement("details");
     details.className="audit-inline-details audit-full-history";
     const summary=document.createElement("summary");
     summary.textContent="Full Schwab order journal and per-order Excel exports";
     journal.before(details);details.append(summary,journal);
   }
   const exportButton=$("audit-export-live");
   exportButton?.addEventListener("click",()=>document.getElementById("export-live-trades")?.click());
   // Keep section refresh controls but show their independent scope.
   [["robinhood-refresh","Refresh Robinhood account only"],
     ["webull-refresh","Refresh Webull account only"],
     ["webull-orders-refresh","Refresh Webull local bot intents only"],
     ["webull-evidence-refresh","Refresh Webull scanner evidence only"],
     ["rh-evidence-refresh","Refresh Robinhood scanner evidence only"],
     ["operations-refresh","Refresh cross-account operations only"]]
     .forEach(([id,msg])=>{const b=$(id);if(b){b.title=msg;b.setAttribute("aria-label",msg);}});
   const robinhoodBadge=$("robinhood-execution-mode");
   if(robinhoodBadge)robinhoodBadge.title="This represents saved order permission. Reconciliation and risk gates are shown below.";
   if($("ai-header-status"))$("ai-header-status").title=
     "Online means Ollama responded with installed-model metadata for the selected model. "+
     "It is NOT proof of a successful inference, AI approval, or trading quality. "+
     "Historical model attribution is recorded per decision.";
   const note=$("workspace-webull-detail");
   if(note&&note.textContent.includes("Open Webull"))note.title="Broker permissions and status are verified separately.";
 }
 document.addEventListener("DOMContentLoaded",mount);
 window.AutoTraderAudit={live,robinhood,robinhoodPortfolio,webullAccount,webullTrader,
   webullPolicy,paper,compactRobinhoodDiagnostics,roRisk,webullRisk,
   robinhoodEvidence,webullEvidence,paperEvidence,paperTradeRationale,
   time:value=>stamp(value).label,mask,statusText,moneySigned,percentSigned,pnlClass,
   decorateTable,drawAudit};
})();
