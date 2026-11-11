const test = require('node:test');
const assert = require('node:assert/strict');
const { computeMacd, chartEvidence } = require('../web/price-trend-chart.js');
const {readFileSync} = require('node:fs');
const {resolve} = require('node:path');

test('two KlineChart instances receive distinct clipping paths', async () => {
  const source = readFileSync(resolve(__dirname, '../web/kline-chart.js')).toString();
  const {KlineChart} = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
  const previous = global.document;
  global.document = {createElementNS: () => ({attributes:{},setAttribute(k,v){this.attributes[k]=v},appendChild(){}})};
  try {
    const one={svg:{appendChild(){}}}, two={svg:{appendChild(){}}};
    KlineChart.prototype._createDefs.call(one);
    KlineChart.prototype._createDefs.call(two);
    assert.notEqual(one.clipId,two.clipId);
  } finally { global.document=previous; }
});

test('KlineChart can leave unavailable RPS dates blank instead of interpolating', async () => {
  const source = readFileSync(resolve(__dirname, '../web/kline-chart.js')).toString();
  const {KlineChart} = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
  const chart = Object.create(KlineChart.prototype);
  chart.cfg = {marginLeft:0,candleSpacing:0,interpolateRps:false};
  chart.visible = {windowStart:0,windowEnd:3,visibleWindow:3};
  chart.bars = ['2026-11-06','2026-11-09','2026-11-10'].map(trading_day=>({trading_day}));
  chart.rpsHistory = [{trading_day:'2026-11-09',rps_20:80}];
  chart._getPlotDims = ()=>({ml:0}); chart._barWidth = ()=>10; chart._rpsToY = x=>100-x;
  for (const name of ['rpsLine20','rpsLine50','rpsLine120','rpsLine250']) chart[name]={setAttribute(k,v){this[k]=v}};
  chart._renderRps();
  assert.equal(chart.rpsLine20.d, 'M15.0,20.0');
});

test('KlineChart clears the prior stock RPS lines if new stock has no RPS', async () => {
  const source = readFileSync(resolve(__dirname, '../web/kline-chart.js')).toString();
  const {KlineChart} = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
  const chart = Object.create(KlineChart.prototype);
  chart.rpsHistory = [];
  for (const name of ['rpsLine20','rpsLine50','rpsLine120','rpsLine250']) chart[name]={d:'M1,2',setAttribute(k,v){this[k]=v}};
  chart._renderRps();
  assert.equal(chart.rpsLine20.d,'');
  assert.equal(chart.rpsLine250.d,'');
});

test('MACD uses chronological QFQ closes with TDX-style EMA12/26 and double histogram', () => {
  const bars = [10, 11, 12].map((close, i) => ({trading_day: `2026-11-0${i+1}`, close}));
  const points = computeMacd(bars);
  assert.equal(points.length, 3);
  assert.equal(points[0].dif, 0);
  assert.equal(points[0].dea, 0);
  const ema12 = 10 + (11 - 10) * 2 / 13;
  const ema26 = 10 + (11 - 10) * 2 / 27;
  assert.ok(Math.abs(points[1].dif - (ema12 - ema26)) < 1e-10);
  assert.ok(Math.abs(points[1].hist - 2 * (points[1].dif - points[1].dea)) < 1e-10);
});

test('rejects a stale or future QFQ price series rather than displaying another day', () => {
  const day = '2026-11-10';
  const valid = {ok:true, price_basis:'tdx_export_qfq', as_of_date:day,
    bars:[{trading_day:day, open:10,high:11,low:9,close:10,volume:100}]};
  assert.equal(chartEvidence(valid, day).bars.length, 1);
  for (const change of [{as_of_date:'2026-11-09'}, {bars:[{...valid.bars[0], trading_day:'2026-11-09'}]},
      {price_basis:'tdx_raw'}, {bars:[{...valid.bars[0],close:0}]}]) {
    assert.throws(() => chartEvidence({...valid,...change},day), /前复权|日期|无效/);
  }
});

test('RPS values never use dates after chart day and missing dates remain missing', () => {
  const day='2026-11-10';
  const payload={ok:true, price_basis:'tdx_export_qfq', as_of_date:day,
    bars:[{trading_day:'2026-11-09',open:1,high:1,low:1,close:1,volume:1},
      {trading_day:day,open:2,high:2,low:2,close:2,volume:2}]};
  const rows=chartEvidence(payload,day,[{trading_day:'2026-11-09',rps_20:70},
    {trading_day:'2026-11-11',rps_20:99}]);
  assert.equal(rows.rpsHistory.length,1);
  assert.equal(rows.rpsHistory[0].trading_day,'2026-11-09');
  assert.equal(rows.rpsAsOf,'2026-11-09');
});
