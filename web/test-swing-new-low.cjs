const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = __dirname;
const filterJs = fs.readFileSync(path.join(root, 'stock-filter.js'), 'utf8');
const analysisJs = fs.readFileSync(path.join(root, 'stock-analysis.js'), 'utf8');
const filterHtml = fs.readFileSync(path.join(root, 'stock-filter.html'), 'utf8');
const record = {date:'2026-11-10',low:8.32,confirmed_valley_date:'2026-10-20',confirmed_valley_low:9.15,waiting_bars:5,close_below_confirmed_valley:true};
function extract(source, start, end) {
  return source.slice(source.indexOf(start), source.indexOf(end, source.indexOf(start)));
}
function escapeHtml(value) {
  return String(value == null ? '' : value).replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}
function filterContext() {
  const ctx = { URLSearchParams, Number, String, Array, form: {elements: []}, sort: {selectedOptions:[{dataset:{order:'desc'}}]}, multi: {}, selectedValues: f => f.selectedOptions.map(o => o.value), esc: escapeHtml, fixed: (v,n) => Number(v).toFixed(n ?? 1) };
  vm.createContext(ctx);
  vm.runInContext(extract(filterJs, '  var multi =', '\n  function esc'), ctx);
  vm.runInContext(extract(filterJs, '  function requestParams(', '\n  function relativeStrengthCell('), ctx);
  vm.runInContext(extract(filterJs, '  function swingCell(', '\n  var priceTrendDialog'), ctx);
  return ctx;
}
test('筛选控件仅选中时发送 new_low_risk，未选中不提交参数', () => {
  assert.match(filterHtml, /<select[^>]*name="swing_observation"[^>]*multiple[^>]*>[\s\S]*?<option value="new_low_risk">/);
  const ctx = filterContext();
  const field = {name:'swing_observation', value:'', selectedOptions:[], disabled:false};
  ctx.form.elements = [field];
  assert.equal(ctx.requestParams(1).has('swing_observation'), false);
  field.selectedOptions = [{value:'new_low_risk'}];
  assert.equal(ctx.requestParams(1).get('swing_observation'), 'new_low_risk');
});
test('筛选结果保留主结构并显示独立新低谨慎证据', () => {
  const ctx = filterContext();
  const html = ctx.swingCell({market:'sh',symbol:'600000',stock_name:'测试',swing_structure:{status:'ok',state:'上涨突破',tendency:'caution',stars:'星级暂缓',underlying_rating:{tendency:'bull',star_count:2},new_low_risk:record,as_of:'2026-11-11',last_bar_date:'2026-11-11'}}, {as_of_date:'2026-11-11'});
  assert.match(html, /上涨突破/);
  assert.match(html, /谨慎/);
  assert.match(html, /星级暂缓/);
  assert.match(html, /2026-11-10/);
  assert.match(html, /8\.32/);
  assert.match(html, /2026-10-20/);
  assert.match(html, /9\.15/);
  assert.match(html, /5 根/);
  assert.match(html, /收盘低于确认波谷/);
  assert.match(html, /data-swing-chart/);
});
test('单股结构卡显示新低证据且主结构与基础评级分离', () => {
  const target = {className:'',innerHTML:'',textContent:''};
  const period = {textContent:''};
  const ctx = {document:{getElementById:id=>id==='swing-structure'?target:period},escapeHtml,swingPoints:()=>'',swingNumber: v=>v == null?'—':Number(v).toFixed(2),Array,Number,String};
  vm.createContext(ctx);
  vm.runInContext(extract(analysisJs, '  function renderSwingStructure(', '\n  function renderSwingChart('),ctx);
  ctx.renderSwingStructure({ok:true,data:{as_of_date:'2026-11-11',price_basis:'tdx_export_qfq',observation:{status:'ok',state:'上涨突破',tendency:'caution',stars:'星级暂缓',underlying_rating:{tendency:'bull',star_count:2},new_low_risk:record,close:8.5,last_bar_date:'2026-11-11'}}});
  for (const value of ['上涨突破','谨慎','星级暂缓','偏多','2026-11-10','8.32','2026-10-20','9.15','5 根','收盘低于确认波谷']) assert.ok(target.innerHTML.includes(value),value);
  assert.doesNotMatch(target.innerHTML, /未知 · 星级暂缓/);
});
test('新低风险字段转义且缺失时不伪造风险', () => {
  const ctx = filterContext();
  const baseline = {status:'ok',state:'上涨突破',tendency:'bull',stars:'★★',as_of:'2026-11-11',last_bar_date:'2026-11-11'};
  const without = ctx.swingCell({market:'sh',symbol:'600000',stock_name:'测试',swing_structure:baseline},{as_of_date:'2026-11-11'});
  assert.doesNotMatch(without, /新低风险/);
  const withRisk = ctx.swingCell({market:'sh',symbol:'600000',stock_name:'测试',swing_structure:{...baseline,new_low_risk:{...record,date:'<script>alert(1)</script>'}}},{as_of_date:'2026-11-11'});
  assert.doesNotMatch(withRisk, /<script>/);
  assert.match(withRisk, /&lt;script&gt;/);
  const noBreak = ctx.swingCell({market:'sh',symbol:'600000',stock_name:'测试',swing_structure:{...baseline,new_low_risk:{...record,close_below_confirmed_valley:false}}},{as_of_date:'2026-11-11'});
  assert.match(noBreak, /收盘未低于确认波谷/);
});
