(function () {
  'use strict';
  var host = document.getElementById('market-index-temperature');
  if (!host) return;
  var dialog = document.getElementById('market-index-history-dialog');
  var title = document.getElementById('market-index-history-title');
  var status = document.getElementById('market-index-history-status');
  var plot = dialog.querySelector('.market-index-history-plot');
  var svg = document.getElementById('market-index-history-svg');
  var macd = document.getElementById('market-index-history-macd');
  var controller, chart, history;
  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (char) {
      return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char];
    });
  }
  function chips(periods, row) {
    if (!periods.length) return '<span class="market-index-empty">无</span>';
    return periods.map(function (n) {
      var ma = row.moving_averages && row.moving_averages[String(n)];
      var tip = '收盘 ' + row.close + ' ｜ MA' + n + ' ' + (ma == null ? '未知' : ma);
      return '<span class="market-index-chip" title="' + esc(tip) + '">' + n + '日</span>';
    }).join('');
  }
  function render(row) {
    var available = (row.above || []).length + (row.below || []).length;
    var label = available ? row.above.length + '/' + available + ' 站上' : '无数据';
    var freshness = row.status === 'stale' ? ' · 数据落后' : '';
    var meta = row.as_of_date
      ? row.market + row.symbol + ' · ' + Number(row.close).toFixed(2) + ' · ' + row.as_of_date + freshness
      : row.market + row.symbol + ' · 本地日线缺失';
    var unknown = row.unavailable && row.unavailable.length
      ? '<div class="market-index-unknown">不足：' + esc(row.unavailable.join('、')) + '日均线</div>' : '';
    return '<article class="market-index-card" role="button" tabindex="0" aria-haspopup="dialog" data-market="' + esc(row.market) + '" data-symbol="' + esc(row.symbol) + '" aria-label="' + esc('查看' + row.name + '历史趋势；均线温度：' + meta) + '" title="' + esc(meta + '；点击查看指数历史趋势、成交量、MACD及波峰波谷；非实时行情') + '">' +
      '<div class="market-index-head"><strong>' + esc(row.name) + '</strong><span>' + esc(label + freshness) + '</span></div>' +
      '<div class="market-index-above" aria-label="站上均线">' + chips(row.above || [], row) + '</div>' +
      '<hr class="market-index-divider">' +
      '<div class="market-index-below" aria-label="未站上均线">' + chips(row.below || [], row) + '</div>' + unknown + '</article>';
  }
  fetch('/api/market-index-temperature', {cache: 'no-store'}).then(function (response) {
    if (!response.ok) throw new Error('HTTP ' + response.status);
    return response.json();
  }).then(function (data) {
    if (!data.ok || !Array.isArray(data.indices) || data.indices.length !== 4) throw new Error('指数数据不完整');
    host.innerHTML = data.indices.map(render).join('');
  }).catch(function (error) {
    host.textContent = '大盘温度读取失败：' + error.message;
  });
  function redraw(viewport) {
    if (!history || !chart) return;
    SwingChart.renderOverlay(history, chart);
    svg.querySelectorAll('text').forEach(function (label) {
      if (label.textContent === '个股RPS') label.remove();
    });
    PriceTrendChart.renderMacd(macd, history.bars, viewport);
    macd.setAttribute('preserveAspectRatio', 'none');
  }
  function validate(payload, card) {
    var bars = payload && payload.bars;
    if (!payload || !payload.ok || payload.price_basis !== 'tdx_index_raw' ||
        payload.market !== card.dataset.market || payload.symbol !== card.dataset.symbol ||
        !Array.isArray(bars) || !bars.length || bars[bars.length - 1].date !== payload.as_of_date ||
        bars.some(function (bar, i) { return bar.date !== bar.trading_day ||
          (i && bar.date <= bars[i - 1].date) ||
          ['open','high','low','close'].some(function (key) { return !Number.isFinite(Number(bar[key])) || Number(bar[key]) <= 0; }) ||
          !Number.isFinite(Number(bar.volume)) || Number(bar.volume) < 0;
        })) throw new Error('指数历史日线日期或价格无效');
  }
  async function showHistory(card) {
    if (controller) controller.abort();
    var request = new AbortController();
    controller = request;
    history = null;
    plot.hidden = true;
    title.textContent = card.querySelector('strong').textContent + ' · 历史趋势';
    status.textContent = '正在读取本地指数日线、成交量及峰谷…';
    if (!dialog.open) dialog.showModal();
    try {
      var qs = new URLSearchParams({market:card.dataset.market,symbol:card.dataset.symbol});
      var responses = await Promise.all([
        fetch('/api/market-index-history?' + qs, {signal:request.signal,cache:'no-store'}),
        import('./kline-chart.js?v=20261117-index-history-a')
      ]);
      var payload = await responses[0].json();
      if (request.signal.aborted || !dialog.open) return;
      if (!responses[0].ok || !payload.ok) throw new Error(payload.error && payload.error.message || '指数历史趋势接口不可用，请重启服务');
      validate(payload, card);
      plot.hidden = false;
      if (!chart) chart = new responses[1].KlineChart(svg, {
        marginRight:48, priceHeightRatio:0.72, volumeHeightRatio:0.24,
        rpsHeightRatio:0, gapRatio:0.02, interpolateRps:false
      });
      history = payload;
      chart.onViewportChange = function (viewport) {
        redraw(viewport);
        dialog.querySelectorAll('[data-index-window]').forEach(function (button) { button.classList.remove('is-active'); });
      };
      chart.load(payload.bars, [], 120);
      redraw(chart.visible);
      dialog.querySelectorAll('[data-index-window]').forEach(function (button) {
        button.classList.toggle('is-active', button.dataset.indexWindow === '120');
      });
      status.textContent = payload.name + ' ' + payload.market + payload.symbol + '｜本地通达信指数原始日线｜截至 ' +
        payload.as_of_date + '｜可浏览 ' + payload.bars.length + ' 根有效K线（初始显示最近120根）｜成交量为通达信原始量；峰谷发生日与确认日见悬停标记';
    } catch (error) {
      if (request.signal.aborted) return;
      plot.hidden = true;
      history = null;
      status.textContent = '指数历史趋势读取失败：' + error.message;
    }
  }
  host.addEventListener('click', function (event) {
    var card = event.target.closest('.market-index-card');
    if (card && host.contains(card)) showHistory(card);
  });
  host.addEventListener('keydown', function (event) {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    var card = event.target.closest('.market-index-card');
    if (card && host.contains(card)) { event.preventDefault(); showHistory(card); }
  });
  dialog.querySelector('.market-index-history-close').addEventListener('click', function () { dialog.close(); });
  dialog.addEventListener('close', function () { if (controller) controller.abort(); history = null; });
  dialog.querySelectorAll('[data-index-window]').forEach(function (button) {
    button.addEventListener('click', function () {
      if (!chart || !history) return;
      chart.setPreset(Number(button.dataset.indexWindow));
      button.classList.add('is-active');
    });
  });
}());
