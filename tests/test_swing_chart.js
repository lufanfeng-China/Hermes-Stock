const test = require('node:test');
const assert = require('node:assert/strict');
const { render, chartEvidence, overlayMarkup } = require('../web/swing-chart.js');

const {readFileSync} = require('node:fs');
const {resolve} = require('node:path');

function node() { return { innerHTML: '', textContent: '', attributes: {}, setAttribute(k, v) { this.attributes[k] = v; } }; }

test('shared renderer plots only matching real QFQ candles and confirmed/candidate pivots', () => {
  const svg = node(), meta = node();
  const payload = {
    symbol: '300017', name: '网宿科技', as_of_date: '2026-11-10', price_basis: 'tdx_export_qfq',
    bars: [
      {date:'2026-11-07',open:9,high:10,low:8,close:9.5},
      {date:'2026-11-10',open:10,high:11,low:9,close:10.5},
      {date:'2026-11-10',open:0,high:0,low:0,close:0},
    ],
    observation: { state:'上涨突破', last_10_peaks:[{date:'2026-11-07',high:10,confirmed:'2026-11-10'}],
      last_10_valleys:[{date:'2026-11-10',low:9,confirmed:'2026-11-10'}],
      candidate_peaks:[{date:'2026-11-10',high:11,waiting_bars:3}], candidate_valleys:[] },
  };
  render(payload, svg, meta);
  assert.match(svg.innerHTML, /data-swing-bar="2026-11-10"/);
  assert.match(svg.innerHTML, /data-swing-mark="confirmed"/);
  assert.match(svg.innerHTML, /data-swing-mark="candidate"/);
  assert.doesNotMatch(svg.innerHTML, /开 0\.00/);
  assert.match(meta.textContent, /通达信前复权.*截至 2026-11-10/);
});

test('swing evidence uses only audited QFQ bars and date-matched RPS without interpolation', () => {
  const day='2026-11-11';
  const data={as_of_date:day,price_basis:'tdx_export_qfq',bars:[
    {date:'2026-11-10',open:10,high:11,low:9,close:10,volume:100},
    {date:day,open:11,high:12,low:10,close:11,volume:150}]};
  const evidence=chartEvidence(data,[{trading_day:'2026-11-10',rps_20:80},{trading_day:'2026-11-12',rps_20:99}]);
  assert.deepEqual(evidence.bars.map(b=>b.trading_day),['2026-11-10',day]);
  assert.deepEqual(evidence.rpsHistory.map(r=>r.trading_day),['2026-11-10']);
  assert.throws(()=>chartEvidence({...data,bars:[data.bars[0]]},[]),/日期|同日/);
  assert.throws(()=>chartEvidence({...data,bars:[data.bars[0],{...data.bars[1],close:0}]},[]),/无效|前复权/);
});

test('pivot overlay shares KlineChart viewport and price scale and hides out-of-window marks', () => {
  const chart={visible:{windowStart:1,windowEnd:3,visibleWindow:2},
    bars:[{trading_day:'2026-11-09'},{trading_day:'2026-11-10'},{trading_day:'2026-11-11'}],
    cfg:{candleSpacing:1},_getPlotDims:()=>({ml:8,plotW:100,priceTop:10,priceH:100}),
    _barWidth:()=>49,_priceToY:p=>110-p*5};
  const data={observation:{state:'区间震荡',box_test:'passed',box_lower:9,box_upper:11,
    last_10_peaks:[{date:'2026-11-09',high:12,confirmed:'2026-11-11'},
      {date:'2026-11-10',high:11,confirmed:'2026-11-11'}],
    candidate_valleys:[{date:'2026-11-11',low:9,waiting_bars:2}]}};
  const html=overlayMarkup(data,chart);
  assert.doesNotMatch(html,/data-date="2026-11-09"/);
  assert.match(html,/data-date="2026-11-10"[^>]*><circle cx="32\.5" cy="55"/);
  assert.match(html,/data-swing-mark="candidate"/);
  assert.match(html,/data-swing-box="verified"/);
  assert.doesNotMatch(overlayMarkup({...data,observation:{...data.observation,box_test:'failed'}},chart),/data-swing-box=/);
});

test('screener dialog wires shared KlineChart, MACD, volume, RPS and viewport controls', () => {
  const html=readFileSync(resolve(__dirname,'../web/stock-filter.html'),'utf8');
  const js=readFileSync(resolve(__dirname,'../web/stock-filter.js'),'utf8');
  assert.match(html,/id="swing-chart-macd"/);
  assert.match(html,/swing-chart-svg \{ width:100%; height:440px/);
  assert.doesNotMatch(html,/swing-chart-svg \{ height:260px/);
  assert.match(html,/data-swing-window="120"/);
  assert.match(js,/new KlineChart\(swingChartSvg/);
  assert.match(js,/SwingChart\.renderOverlay/);
  assert.match(js,/PriceTrendChart\.renderMacd\(swingChartMacd/);
  assert.match(js,/SwingChart\.chartEvidence/);
});

test('shared renderer declines missing real OHLC without faking a chart', () => {
  const svg = node(), meta = node();
  render({observation:{},bars:[]}, svg, meta);
  assert.equal(svg.innerHTML, '');
  assert.match(meta.textContent, /无法绘图/);
});
