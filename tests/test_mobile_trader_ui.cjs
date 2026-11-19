"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const root=path.resolve(__dirname,"..");
const read=file=>fs.readFileSync(path.join(root,file),"utf8");

test("responsive trader controls share existing four broker workspaces",()=>{
 const html=read("web/index.html");
 const css=read("web/mobile-ux.css");
 const js=read("web/mobile-ux.js");
 const backend=read("app/dashboard_server.py");
 assert.match(html,/\/mobile-ux\.css/);
 assert.match(html,/\/mobile-ux\.js/);
 assert.match(backend,/"\/mobile-ux\.css": \("mobile-ux\.css"/);
 assert.match(backend,/"\/mobile-ux\.js": \("mobile-ux\.js"/);
 for(const [name,overview] of [["Schwab","live"],["Robinhood","robinhood"],["Webull","webull"],["Paper","overview"]]){
   assert.ok(js.includes(name),name);
   assert.ok(js.includes('overview:"'+overview+'"'),overview);
 }
 assert.match(js,/window\.AutoTraderUnified/);
 assert.match(js,/window\.showView\?\./);
 assert.match(css,/@media \(max-width:940px\), \(pointer:coarse\) and \(orientation:portrait\)/);
 assert.match(css,/\.mobile-trader-nav/);
 assert.match(css,/env\(safe-area-inset-bottom\)/);
});
test("Robinhood valuation distinguishes unavailable prices from zero and labels outside source",()=>{
 const js=read("web/app.js");
 const u=read("web/mobile-ux.js");
 const backend=read("app/broker_workspace.py");
 assert.match(js,/"Price unavailable"/);
 assert.match(js,/pricedCount===0/);
 assert.match(js,/window\.AutoTraderMobile\?\.renderPortfolio\?\./);
 assert.match(u,/CoinGecko USDC\/USD · indicative/);
 assert.match(u,/This value does not authorize orders/);
 assert.match(backend,/"coingecko_usdc_usd_indicative"/);
 assert.match(backend,/get_display_only_mark\(symbol\)/);
});
test("external price lookup is display-only; no order execution risk gate uses it",()=>{
 const safeModule=read("app/robinhood_portfolio_quotes.py");
 const worker=read("app/robinhood_worker.py");
 const order=read("app/robinhood_order_pass.py");
 assert.match(safeModule,/only for canonical USDC-USD/);
 assert.match(safeModule,/last_updated_at/);
 assert.match(safeModule,/timeout=5/);
 assert.doesNotMatch(worker,/get_display_only_mark|robinhood_portfolio_quotes/);
 assert.doesNotMatch(order,/get_display_only_mark|robinhood_portfolio_quotes/);
});
