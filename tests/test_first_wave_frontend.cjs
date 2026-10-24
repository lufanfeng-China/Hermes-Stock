const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const web = path.join(__dirname, '..', 'web');

async function page(responses) {
  const elements = {};
  for (const id of ['as-of-date', 'status', 'results', 'disclosure', 'load', 'current']) {
    elements[id] = {value: '', textContent: '', innerHTML: '', listeners: {}, addEventListener(event, fn) { this.listeners[event] = fn; }};
  }
  const requests = [], timers = new Map();
  let timerId = 0;
  vm.runInNewContext(fs.readFileSync(path.join(web, 'first-wave-start.js'), 'utf8'), {
    document: {getElementById: id => elements[id]},
    fetch: async url => { requests.push(url); return {json: async () => responses.shift()}; },
    setTimeout: fn => { timers.set(++timerId, fn); return timerId; },
    clearTimeout: id => timers.delete(id),
    URLSearchParams,
  });
  await new Promise(resolve => setImmediate(resolve));
  return {elements, requests, timers};
}

const row = {
  market: 'sh', symbol: '600001', stock_name: '测试<&股', as_of_date: '2026-10-23', signal_date: '2026-10-23',
  current_close: 12.35, classification: 'FIRST_WAVE_ELIGIBLE',
  evidence: {current_open: 11.8, prior_20d_return_pct: 13.45,
    prior_20d_min_volume: 12345, prior_20d_max_volume: 23456, current_volume: 56789,
    volume_multiple: 4.6, day_return_pct: 6.12, prior_volume_spread: 1.9},
};
const success = (main = [row]) => ({ok: true, data_as_of: '2026-10-23', groups: {main}, counts: {main: main.length}});

test('renders only the four-rule candidate group with linked name and full audit evidence', async () => {
  const payload = success();
  payload.groups.first_wave_watch = [{stock_name: '不应出现的旧观察'}];
  payload.groups.rebase_review = [{stock_name: '不应出现的旧复核'}];
  const {elements} = await page([payload]);
  const html = elements.results.innerHTML;
  assert.ok(html.includes('当日四条件候选'));
  assert.equal((html.match(/<h2/g) || []).length, 1);
  assert.ok(html.includes('测试&lt;&amp;股'));
  const href = html.match(/href="([^"]+)"/)[1].replaceAll('&amp;', '&');
  const url = new URL(href, 'https://example.test');
  assert.equal(url.pathname, '/stock-analysis.html');
  assert.equal(url.searchParams.get('market'), 'sh');
  assert.equal(url.searchParams.get('symbol'), '600001');
  assert.equal(url.searchParams.get('name'), row.stock_name);
  for (const [key, value] of Object.entries(row.evidence)) {
    assert.ok(html.includes(key), `missing evidence key ${key}`);
    assert.ok(html.includes(String(value)), `missing evidence value ${value}`);
  }
  for (const text of ['2026-10-23', '12.35', 'FIRST_WAVE_ELIGIBLE']) assert.ok(html.includes(text));
  for (const text of ['30日', 'MA10', 'MA20', 'MA30', 'MA60', '不应出现', '平台', '评分', '主榜', '降级', '重新筑底', 'NaN', 'undefined']) assert.ok(!html.includes(text), text);
  assert.ok(elements.status.textContent.includes('2026-10-23'));
  assert.ok(html.includes('当日开盘 / 收盘（前复权）'));
  assert.ok(html.includes('<dd>11.80 / 12.35</dd>'));
});

test('historical build clears previous-date candidates, polls, and current button resets date', async () => {
  const building = {ok: false, error: {code: 'historical_snapshot_building', progress: {percent: 42, stage: '筛选'}}};
  const historical = {...success([]), is_historical: true};
  const {elements, requests, timers} = await page([success(), building, historical, success()]);
  elements['as-of-date'].value = '2026-10-23';
  await elements.load.listeners.click();
  assert.equal(requests[1], '/api/first-wave-start?as_of_date=2026-10-23');
  assert.equal(elements.results.innerHTML, '', 'never show previous-date candidates while building');
  assert.ok(elements.status.textContent.includes('42% · 筛选'));
  assert.equal(timers.size, 1);
  await [...timers.values()][0]();
  assert.equal(timers.size, 0);
  assert.ok(elements.status.textContent.startsWith('历史'));
  assert.ok(elements.results.innerHTML.includes('当日无同时满足全部四条件的候选'));
  await elements.current.listeners.click();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(elements['as-of-date'].value, '');
  assert.equal(requests.at(-1), '/api/first-wave-start');
});

test('missing evidence remains unknown and request errors remove candidate results', async () => {
  const {elements} = await page([success([{...row, evidence: {}}]), {ok: false, error: {message: '日期不可用'}}]);
  assert.ok(elements.results.innerHTML.includes('—'));
  assert.ok(!elements.results.innerHTML.includes('NaN'));
  await elements.load.listeners.click();
  assert.equal(elements.results.innerHTML, '');
  assert.ok(elements.status.textContent.includes('日期不可用'));
});

test('readable evidence rounds display values while retaining raw audit precision', async () => {
  const detailed = {...row, evidence:{...row.evidence, prior_20d_return_pct:13.841113841113838, volume_multiple:14.149008153990108}};
  const {elements} = await page([success([detailed])]);
  const html = elements.results.innerHTML;
  assert.ok(html.includes('<dd>13.84%</dd>'));
  assert.ok(!html.includes('MA10'));
  assert.ok(html.includes('<dd>14.15 倍</dd>'));
  assert.ok(html.includes('13.841113841113838'), 'raw audit must retain full precision');
});

test('late response from an earlier date cannot overwrite the latest query', async () => {
  let resolveOld;
  const old = new Promise(resolve => { resolveOld = resolve; });
  const latest = {...success([{...row, stock_name:'最新历史候选'}]), data_as_of:'2026-10-16', is_historical:true};
  const {elements} = await page([old, latest]);
  elements['as-of-date'].value = '2026-10-16';
  await elements.load.listeners.click();
  assert.ok(elements.results.innerHTML.includes('最新历史候选'));
  resolveOld(success([{...row, stock_name:'不应覆盖的旧请求'}]));
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(elements.results.innerHTML.includes('最新历史候选'));
  assert.ok(!elements.results.innerHTML.includes('不应覆盖的旧请求'));
  assert.ok(elements.status.textContent.includes('2026-10-16'));
});

test('page stylesheet supports rules, evidence, mobile layout and no retired tier styling', () => {
  const css = fs.readFileSync(path.join(web, 'first-wave-start.css'), 'utf8');
  for (const token of ['.rules', '.rules code', '.fw-grid', '.stock-link', '.candidate-meta', '.eligible', '@media', 'overflow-wrap']) assert.ok(css.includes(token), token);
  for (const token of ['.watch', '.rebase', '.tags', 'header b']) assert.ok(!css.includes(token), token);
});

test('page discloses the four AND rules and their exact windows and boundaries', () => {
  const html = fs.readFileSync(path.join(web, 'first-wave-start.html'), 'utf8');
  for (const text of ['四条件 v4', '全部满足（AND）', 'close[t-1] / close[t-21] - 1', '0% ≤', '≤ 20%', '不要求均线', 'volume[t] ≥ 3 × min(volume[t-20:t-1])', 'close[t] / close[t-1] - 1 ≥ 5%', 'max(volume[t-20:t-1]) / min(volume[t-20:t-1]) ≤ 2.5', 'close[t] > open[t]', '排除当天', '前复权', '不做收益回测']) {
    assert.ok(html.includes(text), `missing rule disclosure: ${text}`);
  }
  for (const asset of ['css', 'js']) assert.ok(html.includes(`/first-wave-start.${asset}?v=20261024-20d-no-ma-v7`));
  for (const id of ['global-nav', 'as-of-date', 'load', 'current', 'status', 'results']) assert.ok(html.includes(`id="${id}"`));
});
