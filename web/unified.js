"use strict";
/* Unified trader experience: presentation and controls only.
 * Existing broker account data, API contracts, CSRF and order guards remain authoritative.
 * No account is armed merely by visiting or changing a workspace.
 */
(function(){
  const ACCOUNTS={
    live:{name:"Schwab",type:"LIVE · STOCKS",home:"live",risk:"live-risk",orders:"live-orders",decisions:"decisions",research:"forecast",mode:"live-worker-mode"},
    robinhood:{name:"Robinhood",type:"LIVE · CRYPTO",home:"robinhood",risk:"robinhood-risk",orders:"robinhood-orders",decisions:"robinhood-decisions",research:"robinhood-forecast",mode:"robinhood-execution-mode"},
    webull:{name:"Webull",type:"LIVE · STOCKS & CRYPTO",home:"webull",risk:"webull-risk",orders:"webull-orders",decisions:"webull-decisions",mode:"webull-order-mode"},
    paper:{name:"Paper",type:"SIMULATED · NO REAL ORDERS",home:"overview",risk:"settings",orders:"trades",decisions:"reviews",mode:"mode-pill"}
  };
  const byId=id=>document.getElementById(id);
  const accountFor=view=>Object.keys(ACCOUNTS).find(key=>Object.values(ACCOUNTS[key]).includes(view))||null;
  let activeAccount=null,working=false;

  function navButton(label,view,icon){
    const button=document.createElement("button");
    button.type="button";button.className="unified-link";
    button.dataset.unifiedView=view;
    button.innerHTML='<span aria-hidden="true">'+icon+'</span><span>'+label+'</span>';
    return button;
  }
  function disclosure(label,className){
    const details=document.createElement("details");
    details.className=className;
    const summary=document.createElement("summary");
    summary.textContent=label;
    details.append(summary);
    return details;
  }
  function setupSidebar(){
    const nav=document.querySelector(".sidebar .side-nav");
    if(!nav||byId("unified-navigation"))return;
    document.body.classList.add("unified-shell");
    const switcher=document.createElement("div");
    switcher.className="unified-switcher";
    switcher.innerHTML='<label for="unified-account-select">Trading account</label>'+
      '<select id="unified-account-select" aria-label="Choose trading account">'+
      '<option value="">All accounts</option>'+
      '<option value="live">Schwab</option><option value="robinhood">Robinhood</option>'+
      '<option value="webull">Webull</option><option value="paper">Paper simulator</option></select>';
    nav.parentNode.insertBefore(switcher,nav);
    const root=document.createElement("div");
    root.id="unified-navigation";root.className="unified-navigation hidden";
    const main=document.createElement("div");main.className="unified-navigation-primary";
    const advanced=disclosure("More account tools","unified-menu-disclosure");
    const shared=disclosure("Shared tools","unified-menu-disclosure");
    shared.append(navButton("Trading operations","operations","▤"),
      navButton("AI workstation","local","✧"),
      navButton("Broker connections","brokers","⌘"));
    root.append(main,advanced,shared);
    nav.insertBefore(root,nav.firstChild);
    byId("unified-account-select").addEventListener("change",event=>{
      const key=event.target.value;
      showView(key?ACCOUNTS[key].home:"workspaces");
    });
    setupNavigation();
  }
  function setupNavigation(){
    const root=byId("unified-navigation");
    if(!root)return;
    const main=root.querySelector(".unified-navigation-primary");
    const more=root.querySelector(".unified-menu-disclosure");
    main.replaceChildren();more.querySelectorAll(".unified-link").forEach(el=>el.remove());
    if(activeAccount){
      const cfg=ACCOUNTS[activeAccount];
      main.append(navButton("Overview",cfg.home,"◈"),
        navButton("Risk & start",cfg.risk,"⚙"),
        navButton("Orders & activity",cfg.orders,"⇄"));
      more.append(navButton("AI decisions",cfg.decisions,"✧"));
      if(cfg.research)more.append(navButton("Market outlook",cfg.research,"◷"));
    }
    root.classList.toggle("hidden",!activeAccount);
  }
  function markNav(view){
    const root=byId("unified-navigation");if(!root)return;
    root.querySelectorAll("[data-unified-view]").forEach(el=>{
      const on=el.dataset.unifiedView===view;
      el.classList.toggle("active",on);
      if(on)el.setAttribute("aria-current","page");
      else el.removeAttribute("aria-current");
    });
  }
  function actionButton(label,action,style){
    const button=document.createElement("button");
    button.className="btn "+style;
    button.type="button";button.dataset.unifiedAction=action;
    button.textContent=label;
    return button;
  }
  function setupDashboard(key,cfg){
    const root=byId("view-"+cfg.home);
    if(!root||root.dataset.unifiedReady)return;
    root.dataset.unifiedReady="true";
    root.classList.add("unified-dashboard");
    const hero=root.querySelector(":scope > .hero-head");
    const panel=hero?.querySelector(".control-panel");
    if(!hero||!panel)return;
    const heading=hero.querySelector("h1");
    if(heading)heading.textContent=cfg.name+" trading";
    const caption=hero.querySelector(".eyebrow");
    if(caption)caption.textContent=cfg.type+" · ACCOUNT WORKSPACE";
    const originalButtons=panel.querySelector(".control-buttons");
    const originalNotes=Array.from(panel.querySelectorAll(":scope > .panel-note"));
    const hiddenActions=disclosure("Additional account actions","unified-menu-disclosure unified-extra-actions");
    if(originalButtons)hiddenActions.append(originalButtons);
    originalNotes.forEach(node=>hiddenActions.append(node));
    const row=document.createElement("div");
    row.className="unified-actions";
    row.append(actionButton(key==="paper"?"Start simulation":"Start trading","start","primary"),
      actionButton("Pause","pause","danger-outline"),
      actionButton("Risk settings","risk","secondary"));
    const feedback=document.createElement("p");
    feedback.className="unified-action-feedback";
    feedback.id="unified-feedback-"+key;
    feedback.setAttribute("role","status");
    feedback.setAttribute("aria-live","polite");
    feedback.textContent=key==="paper"?"Simulated trades only.":"No live orders are placed until you authorize this account.";
    panel.append(row,feedback);
    if(originalButtons||originalNotes.length)panel.append(hiddenActions);

    const existing=Array.from(root.children).filter(node=>node!==hero);
    const notice=existing.find(node=>node.classList.contains("notice"));
    const stats=existing.find(node=>node.classList.contains("stats-grid"));
    const perf=existing.find(node=>node.classList.contains("rh-portfolio-performance"));
    const footer=existing.filter(node=>node.classList.contains("footer-note"));
    const excluded=new Set([hero,notice,stats,perf,...footer].filter(Boolean));
    const diagnostics=disclosure("Execution status & account details","unified-section-disclosure");
    const activity=disclosure("Activity, strategy diagnostics & records","unified-section-disclosure");
    for(const node of existing){
      if(excluded.has(node))continue;
      if(node.classList.contains("content-grid")&&!node.classList.contains("lower-grid"))
        diagnostics.append(node);
      else activity.append(node);
    }
    for(const node of [hero,notice,stats,perf])if(node)root.append(node);
    if(diagnostics.children.length>1)root.append(diagnostics);
    if(activity.children.length>1)root.append(activity);
    footer.forEach(node=>root.append(node));
    if(key==="paper")wrapPaperHistory(perf);
    wrapHoldings(key,perf);
    const mode=byId(cfg.mode);
    if(mode&&typeof MutationObserver!=="undefined"){
      const observer=new MutationObserver(()=>renderMode(key));
      observer.observe(mode,{subtree:true,childList:true,characterData:true,attributes:true,
        attributeFilter:["class"]});
    }
    renderMode(key);
  }
  function wrapPaperHistory(perf){
    if(!perf)return;
    const selectors=[".paper-history-label",".chart-value","#equity-chart",".chart-bottom"];
    const nodes=selectors.map(x=>perf.querySelector(x)).filter(Boolean);
    if(!nodes.length)return;
    const details=disclosure("View simulated equity history","unified-holdings-disclosure");
    nodes[0].parentNode.insertBefore(details,nodes[0]);
    nodes.forEach(node=>details.append(node));
  }
  function wrapHoldings(key,perf){
    if(!perf)return;
    const lookup={
      live:[".broker-holdings-heading","#schwab-perf-holdings"],
      robinhood:[".broker-holdings-detail"],
      webull:[".broker-holdings-heading","#webull-positions"],
      paper:[".broker-holdings-heading","#positions-list"]
    };
    const nodes=lookup[key].map(selector=>perf.querySelector(selector)).filter(Boolean);
    if(!nodes.length)return;
    const details=disclosure("View current holdings","unified-holdings-disclosure");
    nodes[0].parentNode.insertBefore(details,nodes[0]);
    nodes.forEach(node=>details.append(node));
  }
  function setupRiskGuide(key,cfg){
    const root=byId("view-"+cfg.risk);
    if(!root||root.querySelector(".unified-risk-guide"))return;
    const guide=document.createElement("div");
    guide.className="unified-risk-guide";
    const title=document.createElement("div");
    title.innerHTML='<strong>1. Save account risk limits</strong><p>2. Start when the account is authorized. No separate test-trade requirement.</p>';
    const start=actionButton(key==="paper"?"Start simulation":"Start trading","start","primary");
    start.dataset.account=key;
    guide.append(title,start);
    const header=root.querySelector(":scope > .page-header");
    if(header)header.after(guide);
    else root.prepend(guide);
    if(key==="robinhood")collapseRobinhoodAdvanced(root);
  }
  function collapseRobinhoodAdvanced(root){
    const main=root.querySelector("#robinhood-risk-form .settings-main");
    if(!main)return;
    const rows=Array.from(main.children).filter(node=>node.classList.contains("setting-item"));
    if(rows.length<7)return;
    const advanced=disclosure("Advanced entry, exit & cooldown limits","unified-section-disclosure unified-risk-advanced");
    const keep=new Set(rows.slice(0,4));
    for(const row of rows){
      if(row.querySelector("#robinhood-risk-activate"))keep.add(row);
    }
    const first=rows.find(row=>!keep.has(row));
    if(first){
      first.before(advanced);
      rows.forEach(row=>{if(!keep.has(row))advanced.append(row);});
    }
  }
  function renderMode(key){
    const feedback=byId("unified-feedback-"+key);
    const status=byId(ACCOUNTS[key].mode);
    if(!feedback||!status||working)return;
    const value=status.textContent.trim();
    const simulated=key==="paper";
    feedback.textContent=(simulated?"Simulation":"Order permission")+": "+value+
      (simulated?" · virtual funds only":" · broker and per-order safeguards still apply");
  }
  function onViewChange(view){
    const next=accountFor(view);
    if(next!==activeAccount){activeAccount=next;setupNavigation();}
    const select=byId("unified-account-select");
    if(select)select.value=next||"";
    markNav(view);
    if(next)renderMode(next);
  }
  function feedback(key,message,error){
    const node=byId("unified-feedback-"+key);
    if(node){node.textContent=message;node.classList.toggle("is-error",!!error);}
  }
  async function start(key){
    const cfg=ACCOUNTS[key];
    if(key==="paper"){byId("start-btn")?.click();return;}
    if(key==="live"){
      const current=await request("/api/live");
      if(!current.worker_online||!current.armed){
        feedback(key,"The Schwab worker is not active. Open broker connections to finish account activation.",true);
        showView("brokers");return;
      }
      if(current.journal_halted){
        feedback(key,"Trading is halted for reconciliation; resolve the broker order before resuming.",true);
        return;
      }
      if(current.order_permission==="running"){feedback(key,"Schwab trading permission is already active.");return;}
      if(!window.confirm("Start autonomous Schwab trading with REAL MONEY under the saved risk limits? Broker and order checks still apply."))return;
      await request("/api/live/mode",{method:"POST",body:JSON.stringify({mode:"running"})});
      feedback(key,"Schwab order permission enabled; execution still requires broker and risk approval.");
      await refreshAll();return;
    }
    if(key==="robinhood"){
      const policy=await request("/api/robinhood/risk");
      if(policy.enabled===true){feedback(key,"Robinhood permission is already armed. Order checks still apply.");return;}
      if(policy.configured!==true||!policy.account){
        feedback(key,"Save Robinhood account risk limits first, then select Start trading.",true);
        showView(cfg.risk);return;
      }
      if(!window.confirm("Start autonomous Robinhood crypto trading with REAL MONEY using the saved account and risk limits? The first qualifying order may execute."))return;
      await request("/api/robinhood/risk",{method:"POST",body:JSON.stringify({...policy,enabled:true})});
      feedback(key,"Robinhood policy armed. Broker cash, market, AI, order and risk checks still apply.");
      await Promise.allSettled([loadRobinhoodWorkspace(),loadRobinhoodRisk()]);
      return;
    }
    if(key==="webull"){
      const state=await request("/api/webull/trader");
      if(state.risk?.saved!==true){
        feedback(key,"Save Webull risk limits first. Then choose a verified market and account.",true);
        showView(cfg.risk);return;
      }
      if(state.policy?.enabled===true){
        feedback(key,"Webull policy is already armed. New orders still require runtime checks.");
        return;
      }
      if(!((state.policy?.trade_stocks&&state.policy?.stock_account)||
           (state.policy?.trade_crypto&&state.policy?.crypto_account))){
        feedback(key,"Select the verified Webull account and market on Risk & start.",true);
        showView(cfg.risk);return;
      }
      await loadWebullPolicy();
      await webullChangePermission(true); // Uses existing explicit real-money confirmation and CSRF.
      feedback(key,byId("webull-live-feedback")?.textContent||"Webull activation response unavailable.");
    }
  }
  async function pause(key){
    if(key==="paper"){byId("pause-btn")?.click();return;}
    if(key==="live"){
      if(!window.confirm("Pause new Schwab order submissions? Existing accepted orders remain subject to reconciliation."))return;
      await request("/api/live/mode",{method:"POST",body:JSON.stringify({mode:"paused"})});
      feedback(key,"Schwab order submission paused; outstanding broker orders still require reconciliation.");
      await refreshAll();return;
    }
    if(key==="robinhood"){
      if(!window.confirm("Pause new Robinhood crypto orders? Existing broker orders are not canceled."))return;
      const policy=await request("/api/robinhood/risk");
      if(policy.enabled!==true){feedback(key,"Robinhood order permission is already off.");return;}
      await request("/api/robinhood/risk",{method:"POST",body:JSON.stringify({...policy,enabled:false})});
      feedback(key,"Robinhood permission disabled; existing broker orders still require reconciliation.");
      await Promise.allSettled([loadRobinhoodWorkspace(),loadRobinhoodRisk()]);return;
    }
    if(key==="webull"){
      // Local disarm must work even when Webull's accounts endpoint is unavailable.
      const current=await request("/api/webull/trader");
      if(current.policy?.enabled!==true){feedback(key,"Webull trading permission is already off.");return;}
      await request("/api/webull/trader",{method:"POST",body:JSON.stringify({
        policy:{...current.policy,enabled:false},confirmation:""})});
      feedback(key,"Webull order permission paused. Outstanding orders still require reconciliation.");
      await Promise.allSettled([loadWebullTrader(),loadWebullPolicy()]);
    }
  }
  async function onAction(button){
    const key=button.dataset.account||activeAccount;
    if(!key||!ACCOUNTS[key]||working)return;
    if(button.dataset.unifiedAction==="risk"){showView(ACCOUNTS[key].risk);return;}
    working=true;button.disabled=true;
    feedback(key,"Checking "+ACCOUNTS[key].name+" trading permissions…");
    try{
      if(button.dataset.unifiedAction==="start")await start(key);
      else if(button.dataset.unifiedAction==="pause")await pause(key);
    }catch(error){
      const msg=String(error?.message||error||"Unable to update trading permission");
      feedback(key,msg,true);
      if(typeof toast==="function")toast(msg,true);
    }finally{working=false;button.disabled=false;}
  }
  function setupWorkspaceIntro(){
    const toolbar=document.querySelector(".workspace-sort-toolbar");
    if(toolbar){
      const manage=disclosure("Customize account tile order","unified-menu-disclosure unified-workspace-manage");
      toolbar.before(manage);manage.append(toolbar);
    }
    const upcoming=document.querySelector(".workspace-upcoming-grid");
    const planned=upcoming?Array.from(upcoming.querySelectorAll(".workspace-tile.is-coming-soon")):[];
    if(planned.length){
      const details=disclosure("Planned integrations ("+planned.length+")","unified-section-disclosure unified-upcoming-disclosure");
      upcoming.after(details);planned.forEach(tile=>details.append(tile));
    }
  }
  function boot(){
    setupSidebar();
    setupWorkspaceIntro();
    for(const [key,cfg] of Object.entries(ACCOUNTS)){
      setupDashboard(key,cfg);setupRiskGuide(key,cfg);
    }
    const visible=document.querySelector(".view:not(.hidden)");
    onViewChange(visible?.id?.replace(/^view-/,"")||"workspaces");
    document.addEventListener("click",event=>{
      const link=event.target.closest("[data-unified-view]");
      if(link){showView(link.dataset.unifiedView);return;}
      const action=event.target.closest("[data-unified-action]");
      if(action)onAction(action);
    });
  }
  window.AutoTraderUnified={onViewChange,boot};
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",boot,{once:true});
  else boot();
})();
