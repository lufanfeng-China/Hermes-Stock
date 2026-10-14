/** Global navigation — injected into any page with <div id="global-nav"> */
(function () {
  const PAGES = [
    { href: '/stock-analysis.html', label: '股票分析' },
    { href: '/financial-report.html', label: '财报分析' },
    { href: '/watchlist.html', label: '自选股' },
    { href: '/concept-temperature.html', label: '概念温度' },
    { href: '/bottleneck.html', label: '瓶颈股发现' },
  ];

  const currentPath = location.pathname.replace(/\/$/, '') || '/';
  // stock-analysis.html is served at / and /stock-analysis.html
  const isActive = (href) => {
    if (currentPath === '/' && href === '/stock-analysis.html') return true;
    if (currentPath === '/stock-analysis.html' && href === '/stock-analysis.html') return true;
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
