const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('web/good-stock-undervaluation.js', 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));
function setup() {
  const elements = new Map(), listeners = {}, intervals = [], requests = [];
  const element = id => {
    if (!elements.has(id)) elements.set(id, {value:'',textContent:'',innerHTML:'',disabled:false,classList:{add(){},remove(){}},addEventListener(type, fn){this[type]=fn;}});
    return elements.get(id);
  };
  const document = {hidden:false,getElementById:element,addEventListener(type,fn){listeners[type]=fn;}};
  vm.runInNewContext(source, {document,URLSearchParams,AbortController,localStorage:{getItem(){return null},setItem(){}},fetch(url, options){return new Promise((resolve,reject)=>requests.push({url,options,resolve,reject}));},setInterval(fn,ms){intervals.push({fn,ms});return 1;},clearInterval(){},setTimeout(){return 1},clearTimeout(){},window:{addEventListener(){}}});
  const answer = (index, extra={}) => requests[index].resolve({ok:true,json:async()=>({ok:true,total:1,page:1,page_size:50,built_at:'2026-10-30T08:00:00',source_metadata:{market_as_of_date:'2026-10-29',quarterly_period_counts:{'2026-09-30':1}},rows:[{stock_name:'实际股票',symbol:'600000',market:'sh',quarterly_period:'2026-09-30'}],...extra})});
  return {element,document,listeners,intervals,requests,answer};
}
test('visible polling uses no-store, reports real source dates, preserves list on HTTP failure',async()=>{
  const c=setup();
  assert.equal(c.requests[0].options?.cache,'no-store');
  c.answer(0);await tick();
  assert.match(c.element('list-meta').textContent,/生成.*2026-10-30/);
  assert.match(c.element('list-meta').textContent,/行情.*2026-10-29/);
  assert.match(c.element('list-table').innerHTML,/2026-09-30/);
  assert.equal(c.intervals.length,1);
  assert.ok(c.intervals[0].ms>=30000 && c.intervals[0].ms<=60000);
  c.document.hidden=true;c.intervals[0].fn();assert.equal(c.requests.length,1);
  c.document.hidden=false;c.listeners.visibilitychange();assert.equal(c.requests.length,2);
  const before=c.element('list-table').innerHTML, meta=c.element('list-meta').textContent;
  c.requests[1].resolve({ok:false,status:503,json:async()=>({rows:[]})});await tick();
  assert.equal(c.element('list-table').innerHTML,before);
  assert.equal(c.element('list-meta').textContent,meta);
  assert.match(c.element('list-status').textContent,/失败.*保留/);
});
test('latest disclosed period metadata and per-stock report period do not borrow generation date',async()=>{
  const c=setup();c.answer(0,{source_metadata:{latest_period_counts:{'2026-06-30':1}},rows:[{stock_name:'半年报',latest_report_period:'2026-06-30',quarterly_period:null}]});await tick();
  assert.match(c.element('list-meta').textContent,/最新财报期 2026-06-30/);
  assert.match(c.element('list-meta').textContent,/行情 未提供/);
  assert.match(c.element('list-table').innerHTML,/2026-06-30/);
});
test('serial refresh coalesces changed filters and stale response cannot overwrite newest query',async()=>{
  const c=setup();c.answer(0);await tick();
  c.element('f-industry').value='行业甲';c.element('filter-apply').onclick();
  c.element('f-industry').value='行业乙';c.element('filter-apply').onclick();
  c.element('f-industry').value='未应用草稿';
  assert.equal(c.requests.length,2);
  c.answer(1,{rows:[{stock_name:'旧响应'}]});await tick();
  assert.doesNotMatch(c.element('list-table').innerHTML,/旧响应/);
  assert.equal(c.requests.length,3);assert.match(decodeURIComponent(c.requests[2].url),/行业乙/);
  c.answer(2,{built_at:'2026-10-30T09:00:00'});await tick();
  c.intervals[0].fn();assert.match(decodeURIComponent(c.requests[3].url),/行业乙/);
  assert.doesNotMatch(decodeURIComponent(c.requests[3].url),/未应用草稿/);
});
test('actual builder source metadata renders valuation date and financial cutoff',async()=>{
  const c=setup();c.answer(0,{source_metadata:{industry_as_of_counts:{'2026-10-29':5320,unavailable:8},financial_as_of:'2026-10-30',latest_period_counts:{'2026Q3':4686,'2026Q2':640}}});await tick();
  assert.match(c.element('list-meta').textContent,/行情.*2026-10-29/);
  assert.match(c.element('list-meta').textContent,/财报检查截止.*2026-10-30/);
});
