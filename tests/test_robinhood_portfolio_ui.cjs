"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");

const source=fs.readFileSync(path.join(__dirname,"../web/app.js"),"utf8");
const begin=source.indexOf("function robinhoodNumber(value){");
const end=source.indexOf("async function loadRobinhoodWorkspace(){",begin);
assert.ok(begin>=0&&end>begin,"portfolio renderer exists");
const nodes={};
class FakeClassList{
  constructor(){this.items=new Set();}
  add(...names){for(const n of names)this.items.add(n);}
  remove(...names){for(const n of names)this.items.delete(n);}
  contains(name){return this.items.has(name);}
}
class El{
  constructor(tag){
    this.tagName=tag;this.classList=new FakeClassList();this.children=[];
    this.textContent="";this.title="";this._html="";
  }
  set className(v){this.classList.items=new Set(String(v).split(/\s+/).filter(Boolean));}
  get className(){return [...this.classList.items].join(" ");}
  replaceChildren(){this.children=[];}
  append(...xs){this.children.push(...xs);}
  set innerHTML(value){this._html=value;}
}
const required=["robinhood-positions-list","robinhood-positions-status","rh-performance-value",
  "rh-performance-pnl","rh-performance-pct","rh-pnl-coverage","rh-holdings-summary",
  "rh-performance-pnl-label","rh-performance-disclosure"];
for(const id of required)nodes[id]=new El("div");
const context={Number,Intl,String,document:{createElement:tag=>new El(tag)},
  $:id=>nodes[id]||null,
  money:v=>new Intl.NumberFormat("en-US",{style:"currency",currency:"USD",
    minimumFractionDigits:2,maximumFractionDigits:2}).format(Number(v)||0)};
vm.runInNewContext(source.slice(begin,end)+"\nthis.render=renderRobinhoodPortfolio;",context);
const holdings=[
  {symbol:"PEPE-USD",quantity:"3922534",current_price_usd:"0.000000476",
   average_cost_usd:"0.000000432",market_value_usd:"1.867",
   unrealized_pnl_usd:"0.1726",unrealized_pnl_pct:"10.185",
   cost_basis_source:"estimated_broker_fill_history"},
  {symbol:"ZEC-USD",quantity:"0.00527",current_price_usd:"9756.34",
   average_cost_usd:"10100",market_value_usd:"51.4",
   unrealized_pnl_usd:"-1.81",unrealized_pnl_pct:"-3.402",
   cost_basis_source:"estimated_broker_fill_history"}
];
context.render({
  available:true,holdings,position_count:2,order_count:306,cash_usd:"28.30",
  known_holdings_value_usd:"53.26",pnl_covered_holdings:2,pnl_total_holdings:2,
  pnl_completeness:"complete_estimate",unrealized_pnl_usd:"-1.6374",
  unrealized_pnl_pct:"-3.1"
});
assert.ok(nodes["rh-performance-pnl"].textContent.endsWith("$1.64"));
assert.ok(nodes["rh-performance-pnl"].classList.contains("pnl-down"));
assert.match(nodes["rh-performance-value"].textContent,/\$53\.26/);
const table=nodes["robinhood-positions-list"].children.find(x=>x.tagName==="table");
assert.ok(table,"holdings table rendered");
const rows=table.children.find(x=>x.tagName==="tbody").children;
assert.equal(rows.length,2);
assert.equal(rows[0].children[0].children[0].textContent,"PEPE");
assert.equal(rows[1].children[0].children[0].textContent,"ZEC");
assert.ok(rows[0].children[5].classList.contains("pnl-up"));
assert.ok(rows[1].children[5].classList.contains("pnl-down"));
assert.match(rows[0].children[2].textContent,/0\.000000476/);
const partial={available:true,holdings:[holdings[0],{
  ...holdings[1],average_cost_usd:null,unrealized_pnl_usd:null,
  unrealized_pnl_pct:null,cost_basis_source:"unavailable",
  cost_basis_note:"No matching broker purchase fills available"
}],position_count:2,order_count:306,
  known_holdings_value_usd:"53.26",pnl_covered_holdings:1,
  pnl_completeness:"partial_or_unavailable",known_unrealized_pnl_usd:"0.1726",
  known_unrealized_pnl_pct:"10.185"};
context.render(partial);
assert.match(nodes["rh-performance-pnl-label"].textContent,/PARTIAL/);
const table2=nodes["robinhood-positions-list"].children.find(x=>x.tagName==="table");
const zec=table2.children.find(x=>x.tagName==="tbody").children[1];
assert.equal(zec.children[5].textContent,"Unavailable");
assert.equal(zec.children[3].textContent,"Unavailable");
context.render({available:false,reason:"Connection error"});
assert.equal(nodes["rh-performance-pnl"].textContent,"Unavailable");
assert.equal(nodes["rh-performance-value"].textContent,"Unavailable");
console.log("Robinhood P/L UI rendering: gain/loss, high-precision price, partial basis, and API error passed");
