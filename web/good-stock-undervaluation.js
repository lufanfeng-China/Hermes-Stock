(function () {
  const $ = id => document.getElementById(id);
  const esc = value => String(value == null ? '—' : value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const card = (title, value, detail, good) => `<article class="diag-card"><h3>${esc(title)}</h3><strong class="${good === true ? 'ok' : good === false ? 'bad' : ''}">${esc(value)}</strong><p class="muted">${esc(detail || '')}</p></article>`;
  async function run() {
    const symbol = $('symbol').value.trim(); const market = $('market').value;
    if (!/^\d{6}$/.test(symbol)) { $('status').textContent = '请输入 6 位股票代码'; return; }
    $('status').textContent = '读取当前诊断…'; $('result').hidden = true;
    try {
      const r = await fetch(`/api/good-stock-undervaluation?market=${encodeURIComponent(market)}&symbol=${encodeURIComponent(symbol)}`);
      const d = await r.json(); if (!r.ok || !d.ok) throw new Error(d.error?.message || d.reasons?.join('；') || '诊断不可用');
      const q=d.quality||{}, i=d.industry||{}, h=d.own_history||{}, m=d.margin||{}, x=d.quadrant||{}, momentum=d.quarterly_momentum||{};
      $('summary').innerHTML = [
        card('四象限', x.quadrant, `快照日：${d.as_of_date}`, x.complete),
        card('年度质量', q.status, (q.reasons||[]).join('；'), q.status==='QUALITY_ELIGIBLE'),
        card('双估值安全边际', m.status, (m.reasons||[]).join('；'), m.status==='HAS_MARGIN'),
        card('行业 PE / PS 分位', `${i.pe_percentile?.toFixed(1) ?? '—'}% / ${i.ps_percentile?.toFixed(1) ?? '—'}%`, `样本：${i.pe_sample_size ?? '—'} / ${i.ps_sample_size ?? '—'}`, i.status==='AVAILABLE'),
        card('自身历史 PE / PS 分位', `${h.pe_percentile?.toFixed(1) ?? '—'}% / ${h.ps_percentile?.toFixed(1) ?? '—'}%`, `有效日：${h.pe_valid_trading_days ?? '—'} / ${h.ps_valid_trading_days ?? '—'}`, h.status==='AVAILABLE'),
        card('季度经营动量', momentum.status, `报告期：${momentum.period || '—'}`, momentum.improving === true),
      ].join('');
      $('audit').textContent=JSON.stringify(d,null,2); $('result').hidden=false; $('status').textContent=`${d.stock_name || symbol}｜当前快照`;
    } catch (e) { $('status').textContent=`失败：${e.message}`; }
  }
  $('run').addEventListener('click', run); run();
})();
