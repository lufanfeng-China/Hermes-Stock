/** Global navigation — injected into any page with <div id="global-nav"> */
(function () {
  const PAGES = [
    { href: '/stock-score.html', label: '财务评分' },
    { href: '/stock-screener.html', label: '股票筛选' },
    { href: '/financial-report.html', label: '财报分析' },
    { href: '/rps-pool.html', label: 'RPS' },
    { href: '/watchlist.html', label: '自选股' },
    { href: '/concept-analysis.html', label: '概念分析' },
    { href: '/bottleneck.html', label: '瓶颈股发现' },
    { href: '/macd-extreme-gc.html', label: '极值金叉' },
  ];

  const currentPath = location.pathname.replace(/\/$/, '') || '/';
  // stock-score.html is served at / (index.html) and /stock-score.html
  const isActive = (href) => {
    if (currentPath === '/' && href === '/stock-score.html') return true;
    if (currentPath === '/stock-score.html' && href === '/stock-score.html') return true;
    return currentPath === href;
  };

  const container = document.getElementById('global-nav');
  if (!container) return;

  const links = PAGES.map(p => {
    const active = isActive(p.href) ? ' active' : '';
    return `<a href="${p.href}" class="nav-link${active}">${p.label}</a>`;
  }).join('');

  container.innerHTML = `<nav style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px">${links}</nav>`;
})();
