"use strict";
/* Compact, mobile-first view layered onto the existing four account dashboards.
   No broker requests, order approvals or state mutation originate here. */
(function(){
  const CONFIG={
    live:{name:"Schwab",overview:"live",risk:"live-risk",orders:"live-orders",extra:"decisions"},
    robinhood:{name:"Robinhood",overview:"robinhood",risk:"robinhood-risk",orders:"robinhood-orders",extra:"robinhood-decisions"},
    webull:{name:"Webull",overview:"webull",risk:"webull-risk",orders:"webull-orders",extra:"webull-decisions"},
    paper:{name:"Paper",overview:"overview",risk:"settings",orders:"trades",extra:"reviews"}
  };
  let currentAccount=null;
  const $=id=>document.getElementById(id);
  const isAccountView=view=>Object.entries(CONFIG).find(([,c])=>Object.values(c).includes(view))?.[0]||null;

  function navigationButton(label,icon,kind){
    const el=document.createElement("button");
    el.type="button";el.className="mobile-trader-tab";
    el.dataset.mobileTab=kind;el.setAttribute("aria-label",label);
    const glyph=document.createElement("span");glyph.className="mobile-trader-icon";glyph.setAttribute("aria-hidden","true");glyph.textContent=icon;
    const name=document.createElement("span");name.className="mobile-trader-label";name.textContent=label;
    el.append(glyph,name);return el;
  }
  function setupNavigation(){
    if($("mobile-trader-nav"))return;
    const top=document.querySelector(".main-shell .topbar");
    if(!top)return;
    const picker=document.createElement("div");picker.className="mobile-trader-picker";
    const label=document.createElement("label");label.htmlFor="mobile-trader-account";label.textContent="Account";
    const select=document.createElement("select");select.id="mobile-trader-account";
    select.setAttribute("aria-label","Choose trading account");
    for(const [key,name] of [["","All accounts"],["live","Schwab"],["robinhood","Robinhood"],["webull","Webull"],["paper","Paper trading"]]){
      const o=document.createElement("option");o.value=key;o.textContent=name;select.append(o);
    }
    picker.append(label,select);
    const actions=top.querySelector(".top-actions");
    if(actions)actions.before(picker);else top.append(picker);
    select.addEventListener("change",()=>window.showView?.(select.value?CONFIG[select.value].overview:"workspaces"));

    const nav=document.createElement("nav");nav.id="mobile-trader-nav";nav.className="mobile-trader-nav";
    nav.setAttribute("aria-label","Trading workspace navigation");
    nav.append(navigationButton("Accounts","▦","accounts"),
      navigationButton("Overview","◈","overview"),
      navigationButton("Risk","⚙","risk"),
      navigationButton("Activity","⇄","orders"));
    document.body.append(nav);
    nav.addEventListener("click",event=>{
      const button=event.target.closest("[data-mobile-tab]");
      if(!button)return;
      const action=button.dataset.mobileTab;
      if(action==="accounts"){window.showView?.("workspaces");return;}
      if(!currentAccount){window.showView?.("workspaces");return;}
      const to=CONFIG[currentAccount][action];
      if(to)window.showView?.(to);
    });
  }
  function syncView(view){
    const next=isAccountView(view);
    if(next)currentAccount=next;
    const select=$("mobile-trader-account");
    if(select)select.value=view==="workspaces"?"":currentAccount||"";
    const nav=$("mobile-trader-nav");if(!nav)return;
    for(const button of nav.querySelectorAll("[data-mobile-tab]")){
      const k=button.dataset.mobileTab;
      const active=k==="accounts"?view==="workspaces":currentAccount!=null&&CONFIG[currentAccount][k]===view;
      button.classList.toggle("active",active);
      if(active)button.setAttribute("aria-current","page");
      else button.removeAttribute("aria-current");
      button.disabled=k!=="accounts"&&!currentAccount;
    }
  }
  function money(raw){
    if(raw===null||raw===undefined||raw==="")return null;
    if(typeof raw!=="string" && typeof raw!=="number")return null;
    if(!/^(?:0|[1-9]\d*)(?:\.\d+)?$/.test(String(raw)))return null;
    const n=Number(raw);
    if(!Number.isFinite(n) || n>1e12)return null;
    return new Intl.NumberFormat("en-US",{style:"currency",currency:"USD",maximumFractionDigits:2}).format(n);
  }
  function makeText(tag,value,className){
    const el=document.createElement(tag);
    el.textContent=value;if(className)el.className=className;return el;
  }
  function createPortfolioPreview(){
    const root=$("view-robinhood")?.querySelector(".rh-portfolio-performance");
    if(!root||$("unified-robinhood-holdings-peek"))return;
    const box=document.createElement("section");
    box.id="unified-robinhood-holdings-peek";
    box.className="mobile-holding-preview";
    box.setAttribute("aria-label","Current Robinhood crypto holdings");
    box.setAttribute("aria-live","polite");
    box.append(makeText("h3","Your holdings"),makeText("p","Loading positions…","mobile-holding-note"));
    const metrics=root.querySelector(".rh-portfolio-metrics");
    if(metrics)metrics.after(box);else root.append(box);
    const explanation=$("rh-performance-disclosure");
    if(explanation){
      const details=document.createElement("details");
      details.className="mobile-method-disclosure";
      details.append(makeText("summary","How valuation and P/L are calculated"));
      explanation.before(details);details.append(explanation);
    }
  }
  function renderPortfolio(data){
    const box=$("unified-robinhood-holdings-peek");
    if(!box)return;
    box.replaceChildren(makeText("h3","Your holdings"));
    if(!data?.available){
      box.append(makeText("p","Robinhood holdings could not be verified. Refresh the account connection.","mobile-holding-note"));return;
    }
    const holdings=Array.isArray(data.holdings)?data.holdings:[];
    if(!holdings.length){box.append(makeText("p","No broker-reported crypto holdings.","mobile-holding-note"));return;}
    for(const holding of holdings.slice(0,3)){
      const row=document.createElement("div");row.className="mobile-holding-row";
      const left=document.createElement("div");left.className="mobile-holding-identity";
      const symbol=String(holding.symbol||"Asset").replace(/-USD$/,"");
      left.append(makeText("strong",symbol,"mobile-holding-symbol"));
      const n=Number(holding.quantity);
      const quantity=Number.isFinite(n)?new Intl.NumberFormat("en-US",{maximumFractionDigits:6}).format(n)+" units":"Quantity unavailable";
      left.append(makeText("small",quantity));
      const right=document.createElement("div");right.className="mobile-holding-mark";
      right.append(makeText("strong",money(holding.market_value_usd)||"Price unavailable"));
      const source=holding.valuation==="coingecko_usdc_usd_indicative"
        ?"CoinGecko USDC/USD · indicative"
        :holding.valuation==="robinhood_v2_bid_ask_midpoint"?"Robinhood bid/ask · indicative"
        :"No verified quote";
      right.append(makeText("small",source));
      row.append(left,right);box.append(row);
    }
    if(holdings.length>3)box.append(makeText("p","+"+(holdings.length-3)+" additional positions · expand holdings below","mobile-holding-note"));
    const coverage=data.valuation_coverage;
    if(coverage && coverage.priced===0 && holdings.length>0){
      box.append(makeText("p","Quotes unavailable for all holdings; $0 is not a confirmed portfolio value.","mobile-holding-warning"));
    }else if(coverage?.externally_marked){
      box.append(makeText("p","USDC uses a recent external indicative quote. This value does not authorize orders.","mobile-holding-note"));
    }
  }
  function init(){
    setupNavigation();
    createPortfolioPreview();
    const api=window.AutoTraderUnified;
    if(api && typeof api.onViewChange==="function"){
      const original=api.onViewChange.bind(api);
      api.onViewChange=view=>{original(view);syncView(view);};
    }
    const current=document.querySelector(".view:not(.hidden)")?.id?.replace(/^view-/,"")||"workspaces";
    syncView(current);
  }
  window.AutoTraderMobile={renderPortfolio,init};
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init,{once:true});
  else init();
})();
