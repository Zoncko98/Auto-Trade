"use strict";
// Forecast is independent read-only research. No trading, brokerage or credential APIs.
function forecastNode(tag,text,cls) {
  const el=document.createElement(tag);
  if(text!==undefined && text!==null) el.textContent=String(text);
  if(cls)el.className=cls;
  return el;
}
function addForecastRow(parent,label,value){
  const row=forecastNode("div",null,"readiness-item");
  row.appendChild(forecastNode("span",label));
  row.appendChild(forecastNode("strong",value));
  parent.appendChild(row);
}
async function loadForecast(){
  const grid=document.getElementById("forecast-grid");
  const message=document.getElementById("forecast-generated");
  const overview=document.getElementById("forecast-overview");
  if(!grid)return;
  message.textContent="Loading from external AI computer…";
  const data=await request("/api/research/forecast");
  grid.replaceChildren();
  if(!Array.isArray(data.candidates)){
    message.textContent=data.message||"No completed forecast";
    overview.textContent="Market data or model initialization is still pending.";
    return;
  }
  message.textContent="Generated "+formatBrokerDate(data.generated_at)
      +" · Next NYSE opening "+formatBrokerDate(data.target_session_open);
  const ok=Boolean(data.lightgbm_validation&&data.lightgbm_validation.beats_zero_return_baseline);
  overview.textContent=(ok?"LightGBM passed initial holdout, but remains experimental. ":
      "LightGBM did NOT beat its holdout baseline; predictions excluded from candidate ranking. ")+
      (data.ranking_method||"")+" · "+data.symbols_with_data+" securities analyzed.";
  data.candidates.forEach((item,i)=>{
    const card=forecastNode("div",null,"panel");
    card.style.margin="16px 0";card.style.padding="18px";
    card.appendChild(forecastNode("h2","#"+(i+1)+" · "+item.ticker));
    const close=item.reference_close;
    const intro=forecastNode("p","Last historical close: "+money(close)+" on "+item.as_of+" · ");
    const market=forecastNode("a","Source: Yahoo historical chart");
    market.href="https://finance.yahoo.com/quote/"+encodeURIComponent(item.ticker)+"/history/";
    market.target="_blank";market.rel="noopener noreferrer";
    intro.appendChild(market);card.appendChild(intro);
    const ch=item.chronos_bolt||{};
    const range=Array.isArray(ch.scenario_close_range)?
        ch.scenario_close_range.map(x=>money(x)).join(" / "):"Unavailable";
    addForecastRow(card,"Chronos-Bolt lower / median / upper scenario",range);
    addForecastRow(card,"FinBERT news sentiment",(item.finbert||{}).label||"Unavailable");
    addForecastRow(card,"Above 20-session moving average",item.technical&&item.technical.above_sma20?"Yes":"No");
    const trade=item.entry_scenario||{};
    addForecastRow(card,"Illustrative entry reference",trade.reference_breakout==null?"—":money(trade.reference_breakout));
    addForecastRow(card,"Illustrative risk invalidation",trade.risk_invalidation==null?"—":money(trade.risk_invalidation));
    addForecastRow(card,"Illustrative 2R exit",trade.illustrative_2R_exit==null?"—":money(trade.illustrative_2R_exit));
    const unmet=forecastNode("details");
    unmet.appendChild(forecastNode("summary","Unmet confirmations ("+(item.confirmation_unmet||[]).length+")"));
    const ul=forecastNode("ul");
    (item.confirmation_unmet||[]).forEach(v=>ul.appendChild(forecastNode("li",v)));
    unmet.appendChild(ul);card.appendChild(unmet);
    const news=forecastNode("details");
    news.appendChild(forecastNode("summary","Source-linked news ("+(item.news||[]).length+")"));
    const ol=forecastNode("ol");
    (item.news||[]).forEach(n=>{
      const li=forecastNode("li",(n.source||"Publisher")+": "+(n.title||"Headline")+" ");
      try{
        const u=new URL(n.url);
        if(u.protocol==="https:"&&u.hostname==="news.google.com"){
          const a=forecastNode("a","Read source");
          a.href=u.href;a.target="_blank";a.rel="noopener noreferrer";li.appendChild(a);
        }
      }catch(_){}
      ol.appendChild(li);
    });
    news.appendChild(ol);card.appendChild(news);
    card.appendChild(forecastNode("p","Research only. These are not calibrated probabilities or executable prices.","panel-note"));
    grid.appendChild(card);
  });
}
document.addEventListener("DOMContentLoaded",()=>{
  const btn=document.getElementById("forecast-refresh");
  if(btn)btn.addEventListener("click",()=>loadForecast().catch(err=>toast(err.message,true)));
});
