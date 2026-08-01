(function () {
  'use strict';
  var PAGE_SIZE = 20;
  var windowEl = document.getElementById('window');
  var conceptsEl = document.getElementById('concepts');
  var membersEl = document.getElementById('members');
  var conceptMeta = document.getElementById('concept-meta');
  var memberMeta = document.getElementById('member-meta');
  var memberTitle = document.getElementById('member-title');
  var conceptCount = document.getElementById('concept-count');
  var memberCount = document.getElementById('member-count');
  var summaryEl = document.getElementById('ct-summary');
  var pagerEl = document.getElementById('concept-pager');
  var temp = '';
  var selected = '';
  var currentPage = 1;
  var conceptRows = [];

  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (c) {
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
    });
  }
  function pct(value) {
    if (value == null || Number.isNaN(Number(value))) return '—';
    var n = Number(value); return (n >= 0 ? '+' : '') + n.toFixed(2) + '%';
  }
  function color(value) { return Number(value) >= 0 ? 'positive' : 'negative'; }
  function tempPill(row) {
    if (row.temperature == null) return '<span class="pill t2">数据不足</span>';
    return '<span class="pill t' + row.temperature + '">' + row.temperature + ' ' + esc(row.temperature_label) + '</span>';
  }
  function renderSummary(data) {
    var rows = data.concepts || [];
    var counts = [0,1,2,3,4,5].map(function (level) {
      return rows.filter(function (row) { return row.temperature === level; }).length;
    });
    summaryEl.innerHTML = '<div class="stat-card"><div class="val">' + esc(data.as_of_date || '—') + '</div><div class="lbl">数据截至</div></div>' +
      '<div class="stat-card"><div class="val">' + rows.length + '</div><div class="lbl">当前概念数</div></div>' +
      '<div class="stat-card"><div class="val positive">' + counts[5] + '</div><div class="lbl">极热 / 5分</div></div>' +
      '<div class="stat-card"><div class="val">' + counts[4] + '</div><div class="lbl">热门 / 4分</div></div>';
  }
  function totalPages() { return Math.max(1, Math.ceil(conceptRows.length / PAGE_SIZE)); }
  function renderPager() {
    var pages = totalPages();
    if (!conceptRows.length) { pagerEl.innerHTML = ''; return; }
    pagerEl.innerHTML = '<button type="button" data-page="prev"' + (currentPage === 1 ? ' disabled' : '') + '>上一页</button>' +
      '<span class="page-info">第 ' + currentPage + ' / ' + pages + ' 页 · 每页 20 个</span>' +
      '<button type="button" data-page="next"' + (currentPage === pages ? ' disabled' : '') + '>下一页</button>';
    pagerEl.querySelectorAll('button').forEach(function (button) {
      button.addEventListener('click', function () {
        currentPage += button.dataset.page === 'prev' ? -1 : 1;
        renderConceptPage();
      });
    });
  }
  function renderConceptPage() {
    var pages = totalPages();
    if (currentPage > pages) currentPage = pages;
    var start = (currentPage - 1) * PAGE_SIZE;
    var visible = conceptRows.slice(start, start + PAGE_SIZE);
    if (!visible.length) {
      conceptsEl.innerHTML = '<tr><td colspan="7" class="empty">没有符合该温度的概念</td></tr>';
      pagerEl.innerHTML = '';
      return;
    }
    conceptsEl.innerHTML = visible.map(function (row) {
      return '<tr class="concept-row ' + (selected === row.concept_code ? 'selected' : '') + '" data-code="' + esc(row.concept_code) + '"><td>' + tempPill(row) + '</td><td><strong>' + esc(row.concept_name) + '</strong></td><td>' + Number(row.heat_score).toFixed(1) + '</td><td class="' + color(row.median_return_pct) + '">' + pct(row.median_return_pct) + '</td><td>' + Number(row.breadth_pct).toFixed(1) + '%</td><td class="' + color(row.excess_return_pct) + '">' + pct(row.excess_return_pct) + '</td><td>' + row.member_count + '</td></tr>';
    }).join('');
    conceptsEl.querySelectorAll('.concept-row').forEach(function (row) {
      row.addEventListener('click', function () {
        selected = row.dataset.code;
        loadMembers();
        renderConceptPage();
      });
    });
    renderPager();
  }
  async function loadConcepts() {
    conceptsEl.innerHTML = '<tr><td colspan="7" class="empty">加载中…</td></tr>';
    pagerEl.innerHTML = '';
    try {
      var url = '/api/concept-temperature?window=' + encodeURIComponent(windowEl.value) + (temp ? '&temperature=' + temp : '');
      var resp = await fetch(url);
      var data = await resp.json();
      if (!resp.ok || !data.ok) throw new Error(data.error || '加载失败');
      conceptRows = data.concepts;
      conceptMeta.textContent = '截至 ' + data.as_of_date + ' · ' + data.window + '日窗口 · 前复权涨幅 · 至少 ' + data.min_members + ' 只有效成分股';
      conceptCount.textContent = conceptRows.length;
      renderSummary(data);
      renderConceptPage();
    } catch (err) {
      conceptMeta.textContent = '加载失败：' + err.message;
      conceptsEl.innerHTML = '<tr><td colspan="7" class="empty">无法加载概念温度数据</td></tr>';
    }
  }
  async function loadMembers() {
    if (!selected) return;
    membersEl.innerHTML = '<tr><td colspan="5" class="empty">加载中…</td></tr>';
    try {
      var resp = await fetch('/api/concept-temperature/members?window=' + encodeURIComponent(windowEl.value) + '&concept_code=' + encodeURIComponent(selected));
      var data = await resp.json();
      if (!resp.ok || !data.ok) throw new Error(data.error || '加载失败');
      memberTitle.textContent = data.concept.concept_name + ' · 成分股';
      memberCount.textContent = data.stocks.length;
      memberMeta.textContent = '共 ' + data.stocks.length + ' 只有效成分股 · 按 ' + data.window + ' 日前复权涨幅降序 · 截至 ' + data.as_of_date;
      membersEl.innerHTML = data.stocks.map(function (row) {
        var market = row.symbol[0] === '6' ? 'sh' : (row.symbol.startsWith('92') ? 'bj' : 'sz');
        var href = '/stock-score.html?market=' + market + '&symbol=' + encodeURIComponent(row.symbol) + '&name=' + encodeURIComponent(row.stock_name);
        return '<tr><td>' + esc(row.symbol) + '</td><td><a class="stock-link" href="' + href + '">' + esc(row.stock_name) + '</a></td><td class="' + color(row.return_pct) + '">' + pct(row.return_pct) + '</td><td>' + Number(row.latest_close).toFixed(2) + '</td><td>' + Number(row.volume_ratio_5d_20d).toFixed(2) + '</td></tr>';
      }).join('');
    } catch (err) {
      memberMeta.textContent = '加载失败：' + err.message;
      membersEl.innerHTML = '<tr><td colspan="5" class="empty">无法加载成分股</td></tr>';
    }
  }
  windowEl.addEventListener('change', function () {
    selected = ''; currentPage = 1; memberTitle.textContent = '成分股清单'; memberCount.textContent = '0';
    memberMeta.textContent = '点击上方概念查看'; membersEl.innerHTML = '<tr><td colspan="5" class="empty">尚未选择概念</td></tr>';
    loadConcepts();
  });
  document.querySelectorAll('.temp-filter').forEach(function (button) {
    button.addEventListener('click', function () {
      temp = button.dataset.temp; currentPage = 1;
      document.querySelectorAll('.temp-filter').forEach(function (item) { item.classList.toggle('active', item === button); });
      loadConcepts();
    });
  });
  loadConcepts();
}());
