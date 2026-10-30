(() => {
  const $=id=>document.getElementById(id), esc=v=>String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const cats=[['has_margin','质量合格且具安全边际'],['quality_no_margin','质量合格但估值不低'],['quality_ineligible','年度质量未达标'],['evidence_unavailable','估值证据不足'],['not_applicable','行业规则不适用']];
  const labels={QUALITY_ELIGIBLE_HAS_MARGIN:'质量合格 · 安全边际成立',QUALITY_ELIGIBLE_NO_MARGIN:'质量合格 · 当前估值不低',QUALITY_ELIGIBLE:'质量合格',NO_MARGIN:'未形成安全边际',HAS_MARGIN:'安全边际成立',NOT_IMPROVING:'未改善',IMPROVING:'改善中',UNAVAILABLE:'数据不足'};
  const label=v=>labels[v]||v||'—', market=s=>['6','5','9'].includes(s[0])?'sh':['0','3'].includes(s[0])?'sz':['4','8'].includes(s[0])?'bj':null;
  let category='has_margin',page=1, selected=null, timer;
  const recentKey='stock-score-recent-searches';
  const recent=()=>{try{return JSON.parse(localStorage.getItem(recentKey)||'[]')}catch{return[]}};
  const save=r=>{const x=[r,...recent().filter(v=>v.market!==r.market||v.symbol!==r.symbol)].slice(0,6);localStorage.setItem(recentKey,JSON.stringify(x))};
  function showOptions(rows){const d=$('stock-dropdown');d.innerHTML=rows.length?rows.map((r,i)=>`<button type="button" class="search-option" data-i="${i}"><span>${esc(r.stock_name)}</span><span class="search-option-meta">${esc(r.market.toUpperCase())} · ${esc(r.symbol)}</span></button>`).join(''):'<div class="search-option empty">未找到匹配股票</div>';d._rows=rows;d.classList.add('visible')}
  async function suggest(){const q=$('stock-input').value.trim();if(!q){showOptions(recent());return}try{const d=await (await fetch('/api/search/stocks?q='+encodeURIComponent(q)+'&limit=10')).json();showOptions(d.results||[])}catch{showOptions([])}}
  async function diagnose(row){const symbol=row?.symbol||$('stock-input').value.trim(), m=row?.market||market(symbol);if(!m||!/^\d{6}$/.test(symbol)){$('status').textContent='请选择全市场搜索结果，或输入有效的 6 位股票代码';return}selected={market:m,symbol};$('stock-dropdown').classList.remove('visible');$('status').textContent='读取当前诊断…';try{const d=await (await fetch(`/api/good-stock-undervaluation?market=${m}&symbol=${symbol}`)).json();if(!d.ok)throw Error(d.reasons?.join('；')||'诊断不可用');save({market:m,symbol,stock_name:d.stock_name});$('stock-input').value=`${d.stock_name} ${symbol}`;const q=d.quality||{},i=d.industry||{},h=d.own_history||{},x=d.quadrant||{},mo=d.quarterly_momentum||{};const c=(a,b,n)=>`<article class="overview-card"><span class="overview-label">${a}</span><strong class="overview-number ${n?'good':''}">${esc(label(b))}</strong></article>`;$('summary').innerHTML=[c('四象限',x.quadrant,x.complete),c('年度质量',q.status,q.status==='QUALITY_ELIGIBLE'),c('行业 PE / PS 分位',`${i.pe_percentile?.toFixed(1)??'—'}% / ${i.ps_percentile?.toFixed(1)??'—'}%`,i.status==='AVAILABLE'),c('自身历史 PE / PS 分位',`${h.pe_percentile?.toFixed(1)??'—'}% / ${h.ps_percentile?.toFixed(1)??'—'}%`,h.status==='AVAILABLE'),c('季度经营动量',mo.status,mo.improving).replace('</article>',profitEvidence(mo.evidence?.profit_change)+'</article>') ].join('');$('audit').textContent=JSON.stringify(d,null,2);$('result').hidden=false;$('status').textContent=`${d.stock_name}｜当前快照`;}catch(e){$('status').textContent='诊断失败：'+e.message}}
  const filters=()=>({industry:$('f-industry').value,min_annual_score:$('f-score').value,max_industry_pe:$('f-ipe').value,max_industry_ps:$('f-ips').value,max_history_pe:$('f-hpe').value,max_history_ps:$('f-hps').value,momentum:$('f-momentum').value});
  function profitEvidence(p){
    if(!p)return '';
    const valid=v=>v!==null&&v!==undefined&&v!==''&&Number.isFinite(Number(v));
    const money=v=>!valid(v)?'数据不足':`${Number(v)!==0&&Math.abs(Number(v))<0.01?Number(v).toPrecision(4):Number(v).toLocaleString('zh-CN',{maximumFractionDigits:2})}元`;
    const percent=valid(p.yoy_pct)?`同比 ${Number(p.yoy_pct).toFixed(2)}%`:(valid(p.previous)&&Number(p.previous)===0?'同比不可计算（同期为0）':'同比数据不足');
    const formula=p.formula||'（本期扣非利润－上年同期扣非利润）÷｜上年同期扣非利润｜×100%；零基期仅比较金额方向';
    return `<small class="profit-change" title="${esc(formula)}">扣非：${esc(p.label||'数据不足')} · ${esc(percent)}<br>本期 ${esc(p.current_period||'—')}：${esc(money(p.current))}<br>同期 ${esc(p.previous_period||'—')}：${esc(money(p.previous))}</small>`;
  }
  const pricePercentileText=r=>r.price_percentile==null?'—':`${r.price_percentile.toFixed(1)}%`;
  let appliedFilters=filters(), listVersion=0, listBusy=false, pendingList=null, listAbort=null;
  function snapshotMeta(d){
    const s=d.source_metadata||d.sources||{};
    const marketDate=s.market_as_of_date||s.qfq_latest_date||s.market?.as_of_date||d.market_as_of_date||Object.keys(s.industry_as_of_counts||{}).filter(day=>day!=='unavailable').sort().join(' / ');
    const financialDate=s.financial_as_of||'未提供';
    const periods=s.quarterly_period_counts||s.latest_period_counts||d.quarterly_period_counts;
    const periodText=periods&&typeof periods==='object'?Object.entries(periods).map(([period,count])=>`${period} (${count}只)`).join(' / '):'';
    return `${d.total} 只 · 生成 ${d.built_at||'未提供'} · 估值行情 ${marketDate||'未提供'} · 财报检查截止 ${financialDate} · 最新财报期 ${periodText||'见每行实际期（汇总未提供）'}`;
  }
  function loadList(automatic=false){
    if(automatic&&(document.hidden||listBusy))return;
    const version=++listVersion;
    pendingList={version,qs:new URLSearchParams({category,page:String(page),page_size:'50',...appliedFilters})};
    if(!listBusy)void drainList();
  }
  async function drainList(){
    const request=pendingList;pendingList=null;listBusy=true;
    listAbort=new AbortController();
    const timeout=setTimeout(()=>listAbort?.abort(),15000);
    $('list-status').textContent='正在核对最新快照…';
    try{
      const response=await fetch('/api/good-stock-undervaluation-list?'+request.qs,{cache:'no-store',signal:listAbort.signal});
      if(!response.ok)throw Error(`HTTP ${response.status}`);
      const d=await response.json();
      if(d.ok===false||!Array.isArray(d.rows))throw Error(d.error?.message||'清单数据不可用');
      if(request.version!==listVersion)return;
      renderList(d);
      $('list-status').textContent='已读取已发布快照 · 页面可见时每45秒自动核对';
    }catch(e){
      if(request.version===listVersion)$('list-status').textContent='刷新失败：'+e.message+'；保留上次成功清单与日期，稍后自动重试';
    }finally{
      clearTimeout(timeout);listAbort=null;listBusy=false;
      if(pendingList)void drainList();
    }
  }
  function renderList(d){$('list-meta').textContent=snapshotMeta(d);$('category-tabs').innerHTML=cats.map(([id,name])=>`<button data-c="${id}" class="${id===category?'active':''}">${name}</button>`).join('');$('list-table').innerHTML='<thead><tr><th>股票</th><th>二级行业</th><th>年度质量分</th><th>行业 PE / PS 分位</th><th>自身历史 PE / PS 分位</th><th>股价分位<br><small>5年/全历史</small></th><th>季度动量<br><small>最新财报期</small></th></tr></thead><tbody>'+d.rows.map(r=>`<tr><td class="stock-cell"><a class="stock-link" href="/stock-analysis.html?market=${encodeURIComponent(r.market)}&symbol=${encodeURIComponent(r.symbol)}&name=${encodeURIComponent(r.stock_name||'')}"><strong>${esc(r.stock_name)}</strong><span>${esc(r.symbol)}</span></a></td><td>${esc(r.industry)}</td><td>${esc(r.annual_score)}</td><td class="metric">${r.industry_pe_percentile?.toFixed(1)??'—'}% / ${r.industry_ps_percentile?.toFixed(1)??'—'}%</td><td class="metric">${r.history_pe_percentile?.toFixed(1)??'—'}% / ${r.history_ps_percentile?.toFixed(1)??'—'}%</td><td class="metric">${pricePercentileText(r)}<br><small>${esc(r.price_percentile_label)}</small></td><td>${esc(label(r.quarterly_momentum))}<br><small>${esc(r.latest_report_period||r.quarterly_period||'—')}</small><br>${profitEvidence(r.quarterly_profit_change)}</td></tr>`).join('')+'</tbody>';$('page-label').textContent=`第 ${d.page} 页 / ${Math.max(1,Math.ceil(d.total/d.page_size))} 页`;$('list-prev').disabled=d.page<=1;$('list-next').disabled=d.page*d.page_size>=d.total}
  $('stock-input').addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(suggest,180)});$('stock-input').addEventListener('focus',suggest);$('stock-dropdown').addEventListener('click',e=>{const b=e.target.closest('[data-i]');if(b)diagnose($('stock-dropdown')._rows[+b.dataset.i])});$('stock-search-form').addEventListener('submit',e=>{e.preventDefault();diagnose(selected)});$('category-tabs').addEventListener('click',e=>{const b=e.target.closest('[data-c]');if(b){category=b.dataset.c;page=1;loadList()}});$('list-prev').onclick=()=>{page--;loadList()};$('list-next').onclick=()=>{page++;loadList()};$('filter-apply').onclick=()=>{appliedFilters=filters();page=1;loadList()};$('filter-reset').onclick=()=>{['f-industry','f-score','f-ipe','f-ips','f-hpe','f-hps','f-momentum'].forEach(id=>$(id).value='');appliedFilters=filters();page=1;loadList()};loadList();
  const refreshInterval=setInterval(()=>loadList(true),45000);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)loadList(true)});
  window.addEventListener('pagehide',()=>{clearInterval(refreshInterval);listAbort?.abort()});
})();