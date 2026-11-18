const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = __dirname;
const read = name => fs.readFileSync(path.join(root, name), 'utf8');
const extract = (source, start, end) => source.slice(source.indexOf(start), source.indexOf(end, source.indexOf(start)));
const escapeHtml = value => String(value == null ? '' : value).replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const pressure = {status:'sustained',shape:'orthodox_down',peaks:[{date:'2026-10-01',confirmed:'2026-10-03',high:12},{date:'2026-10-06',confirmed:'2026-10-08',high:11},{date:'2026-10-10',confirmed:'2026-10-12',high:10}],lines:{AB:9.8,AC:9.6,BC:9.7},key_price:9.7,trigger_date:'2026-10-13',trigger_close:10,c_confirmed:'2026-10-12',trigger_age:3,days_above_after_trigger:2,latest_close:10.2,as_of:'2026-10-15'};
function filterContext() {
  const src = read('stock-filter.js');
  const ctx = {URLSearchParams,form:{elements:[]},sort:{selectedOptions:[{dataset:{order:'desc'}}]},selectedValues:field=>field.selectedOptions.map(o=>o.value),esc:escapeHtml,fixed:(v,n)=>Number(v).toFixed(n??1)};
  vm.createContext(ctx);
  vm.runInContext(extract(src,'  var multi =','\n  function esc'),ctx);
  vm.runInContext(extract(src,'  function requestParams(','\n  function relativeStrengthCell('),ctx);
  vm.runInContext(extract(src,'  function swingCell(','\n  var priceTrendDialog'),ctx);
  return ctx;
}
test('screener cache-busts both changed frontend scripts and labels overlay as observation', () => {
  const html=read('stock-filter.html');
  const analysis=read('stock-analysis.html');
  assert.match(html,/swing-chart\.js\?v=20261112-pressure-line-v1/);
  assert.match(html,/stock-filter\.js\?v=20261112-pressure-line-v2/);
  assert.match(analysis,/swing-chart\.js\?v=20261112-pressure-line-v1/);
  assert.match(analysis,/stock-analysis\.js\?v=20261112-pressure-line-v1/);
  assert.match(html,/压力线.*早期观察/);
});
test('pressure_line is an optional selection in existing multi-select and sent only when selected', () => {
  assert.match(read('stock-filter.html'), /<select[^>]*name="swing_observation"[^>]*multiple[^>]*>[\s\S]*?<option value="pressure_line">/);
  const ctx=filterContext(), field={name:'swing_observation',selectedOptions:[],disabled:false};
  ctx.form.elements=[field];
  assert.equal(ctx.requestParams(1).has('swing_observation'),false);
  field.selectedOptions=[{value:'new_low_risk'},{value:'pressure_line'}];
  assert.equal(ctx.requestParams(1).get('swing_observation'),'new_low_risk,pressure_line');
});
test('screener keeps structural rating and audited chart link without the highlighted pressure details', () => {
  const ctx=filterContext();
  const html=ctx.swingCell({market:'sh',symbol:'600000',stock_name:'测试',swing_structure:{status:'ok',state:'下降趋势',tendency:'bear',stars:'★',as_of:pressure.as_of,last_bar_date:pressure.as_of,pressure_line:pressure}},{as_of_date:pressure.as_of});
  const visible=html.replace(/<[^>]+>/g,'');
  assert.match(visible,/下降趋势 · 偏空 · ★/);
  for (const text of ['下降压力线','早期观察','冻结关键价','AB 9.80','触发后5日延续']) assert.ok(!visible.includes(text),text);
  assert.match(html,/data-swing-chart="1"/);
  assert.match(html,/data-pressure-trigger-date="2026-10-13"/);
  assert.match(html,/data-pressure-key="9.7"/);
  const poisoned=ctx.swingCell({market:'sh',symbol:'600000',stock_name:'测试',swing_structure:{status:'ok',state:'下降趋势',tendency:'bear',as_of:pressure.as_of,last_bar_date:pressure.as_of,pressure_line:{...pressure,trigger_date:'<img src=x onerror=alert(1)>'}}},{as_of_date:pressure.as_of});
  assert.doesNotMatch(poisoned,/<img/);
  assert.match(poisoned,/&lt;img/);
  assert.match(read('stock-filter.js'),/observation\.pressure_line\?\.trigger_date !== trigger\.dataset\.pressureTriggerDate/);
});
test('audited QFQ pressure overlay projects three lines to trigger valid bar and marks frozen price', () => {
  const chartModule=require('./swing-chart.js');
  const dates=['2026-10-01','2026-10-03','2026-10-06','2026-10-08','2026-10-10','2026-10-12','2026-10-13','2026-10-14','2026-10-15'];
  const bars=dates.map((date,i)=>({date,trading_day:date,open:9.2,high:i===0?12:i===2?11:i===4?10:10.5,low:8,close:i===6?10:i===8?10.2:9.5,volume:100}));
  const chartPressure={...pressure,lines:{AB:9,AC:9,BC:9},key_price:9,trigger_age:1};
  const data={as_of_date:pressure.as_of,price_basis:'tdx_export_qfq',bars,observation:{status:'ok',as_of:pressure.as_of,last_bar_date:pressure.as_of,pressure_line:chartPressure}};
  const chart={bars,visible:{windowStart:0,windowEnd:9},cfg:{candleSpacing:2},_getPlotDims:()=>({ml:40,plotW:900,priceTop:0,priceH:400}),_visibleBars:()=>bars,_barWidth:()=>8,_priceToY:v=>300-(v-8)*40};
  const html=chartModule.overlayMarkup(data,chart);
  for(const label of ['A','B','C']) assert.match(html,new RegExp('data-pressure-peak="'+label+'"'));
  for(const line of ['AB','AC','BC']) assert.match(html,new RegExp('data-pressure-line="'+line+'"'));
  assert.match(html,/data-pressure-trigger="2026-10-13"/);
  assert.match(html,/data-pressure-key="9"/);
  assert.match(html,/data-pressure-key-path="1"/); // daily maximum of AB/AC/BC on valid-bar axis
  assert.match(html,/data-pressure-c-peak="10"/); // current confirmed C peak reference
  assert.match(html,/确认于 2026-10-12/);
  assert.match(html,/x2="104"/); // valid-bar index 6, not calendar-day spacing
  // Eligibility is based on the highest of three lines, not all three being positive.
  const mixedLines={...data,observation:{...data.observation,pressure_line:{...pressure,lines:{AB:-1,AC:9.7,BC:9.2}}}};
  assert.match(chartModule.overlayMarkup(mixedLines,chart),/data-pressure-trigger="2026-10-13"/);
  assert.doesNotMatch(chartModule.overlayMarkup({...data,bars:[]},chart),/data-pressure-/);
  assert.doesNotMatch(chartModule.overlayMarkup(data,{...chart,bars:bars.map((b,i)=>i===0?{...b,high:99}:b)}),/data-pressure-/);
  assert.doesNotMatch(chartModule.overlayMarkup({...data,observation:{...data.observation,pressure_line:{...pressure,trigger_close:20}}},chart),/data-pressure-/);
  assert.doesNotMatch(chartModule.overlayMarkup({...data,observation:{...data.observation,pressure_line:{...pressure,peaks:[...pressure.peaks.slice(0,2),{...pressure.peaks[2],date:'2026-10-11'}]}}},chart),/data-pressure-/);
  assert.doesNotMatch(chartModule.overlayMarkup(data,{...chart,_visibleBars:()=>bars.slice(7),visible:{windowStart:7,windowEnd:9}}),/data-pressure-line/);
});
test('analysis chart refuses absent, non-QFQ, or mismatched dates before drawing', () => {
  const {render}=require('./swing-chart.js');
  const svg={innerHTML:'old',setAttribute:()=>{}},meta={textContent:''};
  render({price_basis:'tdx_export_qfq',as_of_date:pressure.as_of,bars:[],observation:{pressure_line:pressure}},svg,meta);
  assert.equal(svg.innerHTML,'');
  assert.match(meta.textContent,/无法绘图/);
  render({price_basis:'raw',as_of_date:pressure.as_of,bars:[{date:pressure.as_of,open:1,high:2,low:1,close:2}]},svg,meta);
  assert.equal(svg.innerHTML,'');
});
test('analysis card shows pressure observation with trigger and continuation without changing stars', () => {
  const src=read('stock-analysis.js'), target={className:'',innerHTML:'',textContent:''}, period={textContent:''};
  const ctx={document:{getElementById:id=>id==='swing-structure'?target:period},escapeHtml,swingPoints:()=>'',swingNumber:v=>v==null?'—':Number(v).toFixed(2)};
  vm.createContext(ctx);
  vm.runInContext(extract(src,'  function renderSwingStructure(','\n  function renderSwingChart('),ctx);
  ctx.renderSwingStructure({ok:true,data:{as_of_date:pressure.as_of,price_basis:'tdx_export_qfq',observation:{status:'ok',state:'下降趋势',tendency:'bear',stars:'★',close:10.2,last_bar_date:pressure.as_of,pressure_line:{...pressure,trigger_date:'<img src=x onerror=alert(1)>'}}}});
  for(const text of ['压力线','★','9.70','AB 9.80','AC 9.60','BC 9.70','30','5','2','早期观察','&lt;img']) assert.ok(target.innerHTML.includes(text),text);
  assert.doesNotMatch(target.innerHTML,/<img|反转确认|升星/);
});
