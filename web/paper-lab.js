'use strict';const el=x=>document.getElementById(x);const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));let csrf='';
async function api(path,method='GET'){const r=await fetch(path,{method,credentials:'same-origin',headers:method==='POST'?{'X-CSRF-Token':csrf}:{}});const d=await r.json();if(!r.ok)throw Error(d.error||'Request failed');return d}
async function refresh(){const d=await api('/api/paper-lab');el('schedule').textContent=d.schedule.enabled?'Disable hourly research':'Enable hourly research';for(const market of ['equity','crypto']){const a=d.accounts[market];el(market).textContent='Virtual equity $'+a.virtual_equity.toFixed(2)+' | net paper P/L $'+a.paper_net.toFixed(2)+' | predictions '+a.predictions+' | settled '+a.settled+' | accuracy '+(a.accuracy===null?'N/A':(a.accuracy*100).toFixed(1)+'%')}
el('records').innerHTML=d.records.map(r=>'<tr><td>'+esc(r.symbol)+'</td><td>'+esc(r.direction)+'</td><td>'+r.hours+'</td><td>'+(r.outcome?(r.outcome.correct?'Correct':'Incorrect'):'Pending')+'</td><td>'+(r.outcome&&r.direction==='UP'?'$'+Number(r.outcome.net).toFixed(2):'-')+'</td><td>'+esc(r.reason)+'</td></tr>').join('')||'<tr><td colspan=6>No results yet</td></tr>'}
el('refresh').onclick=()=>refresh().catch(e=>el('message').textContent=e.message);
el('run').onclick=async()=>{el('run').disabled=true;el('message').textContent='Running research...';try{const r=await api('/api/paper-lab/run','POST');el('message').textContent='Predictions: '+r.added.join(', ')+'; scored: '+r.settled+'; unavailable: '+Object.keys(r.errors).join(', ');await refresh()}catch(e){el('message').textContent=e.message}finally{el('run').disabled=false}};
api('/api/session').then(s=>{csrf=s.csrf;return refresh()}).catch(e=>el('message').textContent=e.message);


el('schedule').onclick=async()=>{try{
 const current=await api('/api/paper-lab');
 const enabled=!current.schedule.enabled;
 const response=await fetch('/api/paper-lab/schedule',{method:'POST',credentials:'same-origin',
 headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify({enabled})});
 const result=await response.json();
 if(!response.ok)throw Error(result.error||'Schedule unavailable');
 el('message').textContent=enabled?'Hourly research enabled':'Automatic research disabled';
 await refresh();
}catch(e){el('message').textContent=e.message}};
