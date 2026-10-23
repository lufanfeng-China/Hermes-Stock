(function () {
  const $ = id => document.getElementById(id);
  const esc = value => String(value == null ? '—' : value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const label = value => ({QUALITY_ELIGIBLE_HAS_MARGIN:'质量合格 · 估值安全边际成立',QUALITY_ELIGIBLE_NO_MARGIN:'质量合格 · 当前估值不低',QUALITY_ELIGIBLE:'质量合格',NO_MARGIN:'未形成双估值安全边际',HAS_MARGIN:'双估值安全边际成立',NOT_IMPROVING:'未改善',IMPROVING:'改善中'}[value] || value || '—');
  const card = (title, value, detail, good) => `<article class="diag-card"><h3>${esc(title)}</h3><div class="diag-value ${good === true ? 'ok' : good === false ? 'bad' : ''}">${esc(label(value))}</div><p class="diag-detail">${esc(detail || '')}</p></article>`;
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
  let listPage=1;
  async function loadList() { const category=$('list-category').value; $('list-status').textContent='加载清单…'; const d=await (await fetch('/api/good-stock-undervaluation-list?category='+encodeURIComponent(category)+'&page='+listPage+'&page_size=50')).json(); $('list-status').textContent=`共 ${d.total} 只｜第 ${d.page} 页｜快照：${d.built_at||'—'}`; $('list-table').innerHTML='<thead><tr><th>股票</th><th>行业</th><th>年度分</th><th>行业 PE/PS</th><th>自身 PE/PS</th><th>季度动量</th></tr></thead><tbody>'+d.rows.map(r=>`<tr><td>${esc(r.stock_name)} ${esc(r.symbol)}</td><td>${esc(r.industry)}</td><td>${esc(r.annual_score)}</td><td>${r.industry_pe_percentile?.toFixed(1)??'—'}% / ${r.industry_ps_percentile?.toFixed(1)??'—'}%</td><td>${r.history_pe_percentile?.toFixed(1)??'—'}% / ${r.history_ps_percentile?.toFixed(1)??'—'}%</td><td>${esc(label(r.quarterly_momentum))}</td></tr>`).join('')+'</tbody>'; $('list-prev').disabled=d.page<=1; $('list-next').disabled=d.page*d.page_size>=d.total; }
  $('list-category').addEventListener('change', () => { listPage=1; loadList().catch(e => { $('list-status').textContent='加载失败：'+e.message; }); });
  $('list-prev').addEventListener('click',()=>{listPage--;loadList()}); $('list-next').addEventListener('click',()=>{listPage++;loadList()});
  $('run').addEventListener('click', run); run(); loadList().catch(e => { $('list-status').textContent='加载失败：'+e.message; });
})();
