const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
async function render(change,status='NOT_IMPROVING'){
 const elements=new Map(),el=id=>{if(!elements.has(id))elements.set(id,{value:'',textContent:'',innerHTML:'',classList:{add(){},remove(){}},addEventListener(){}});return elements.get(id)};
 const data={ok:true,total:1,page:1,page_size:50,rows:[{market:'sz',symbol:'002230',stock_name:'科大讯飞',latest_report_period:'2026Q3',quarterly_momentum:status,quarterly_profit_change:change}]};
 vm.runInNewContext(fs.readFileSync('web/good-stock-undervaluation.js','utf8'),{document:{hidden:false,getElementById:el,addEventListener(){}},window:{addEventListener(){}},URLSearchParams,AbortController,localStorage:{getItem(){return null}},fetch:async()=>({ok:true,json:async()=>data}),setInterval(){},clearInterval(){},setTimeout(){},clearTimeout(){}});
 await new Promise(resolve=>setImmediate(resolve));return el('list-table').innerHTML;
}
test('loss expansion shows actual two-period profit and negative economic growth',async()=>{
 const html=await render({current:-20,previous:-10,delta:-10,yoy_pct:-100,direction:'deteriorating',label:'亏损扩大',current_period:'2026Q3',previous_period:'2025Q3'});
 assert.match(html,/亏损扩大/);assert.match(html,/-100\.00%/);assert.match(html,/-20/);assert.match(html,/-10/);assert.match(html,/2025Q3/);
});
test('zero base is not displayed as zero percent or missing prior amount',async()=>{
 const html=await render({current:10,previous:0,delta:10,yoy_pct:null,direction:'improving',label:'增盈',current_period:'2026Q3',previous_period:'2025Q3'},'IMPROVING');
 assert.match(html,/同期为0/);assert.doesNotMatch(html,/同比 0\.00%/);
});
test('missing evidence is disclosed rather than coerced to zero',async()=>{
 const html=await render({current:null,previous:null,yoy_pct:null,direction:'unavailable',label:'数据不足'},'UNAVAILABLE');
 assert.match(html,/数据不足/);assert.doesNotMatch(html,/同期为0/);
});
