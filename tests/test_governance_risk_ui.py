"""Offline contract tests: execute the real governance renderer in Node, no server."""
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / 'web/stock-analysis.js'
HTML = ROOT / 'web/stock-analysis.html'


class GovernanceRiskUIContract(unittest.TestCase):
    def run_ui(self, body):
        source = JS.read_text()
        self.assertIn('function renderGovernanceRisk(', source)
        start = source.index('  function renderGovernanceRisk(')
        end = source.index('  function renderCompositeFinancialHealth(', start)
        harness = r'''
const assert = require('node:assert/strict');
class Element {
  constructor(tag='div') { this.tagName=tag; this.children=[]; this.textContent=''; this.className=''; this.open=false; this.listeners={}; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children=nodes; this.textContent=''; }
  addEventListener(name, callback) { this.listeners[name]=callback; }
  showModal() { this.open=true; }
  close() { this.open=false; }
  get text() { return this.textContent + this.children.map(x=>x.text).join(' '); }
}
const elements = new Map();
const document = {getElementById: id => {if(!elements.has(id)) elements.set(id,new Element()); return elements.get(id);}, createElement: tag=>new Element(tag)};
const state = {};
const el = id=>document.getElementById(id);
const item = (code, level='normal', complete=true, deduction=0) => ({code,title:code,level,complete,deduction,ratio_pct:30,label:level,color:level==='critical'?'red':level==='normal'?'blue':'yellow',reason:'backend reason',evidence:{source:'公告',date:'2026-10-20',numerator:30,denominator:100},rule_results:[{title:'规则',status:'not_triggered',reason:'未触发'}]});
'''
        result = subprocess.run(['node', '-e', harness + source[start:end] + '\n' + body], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_independent_region_and_backend_binding(self):
        html = HTML.read_text()
        self.assertIn('id="governance-risk-section"', html)
        self.assertLess(html.index('id="financial-health-composite"'), html.index('id="governance-risk-section"'))
        self.assertLess(html.index('id="governance-risk-section"'), html.index('<section class="health-comparison-section"'))
        source = JS.read_text()
        self.assertIn('renderGovernanceRisk(payload.governance_risk)', source)
        self.run_ui('''
renderGovernanceRisk({original_score:72,adjusted_score:57,complete:true,items:[item('major_shareholder_pledge','watch',true,5),item('related_sales','high',true,10)]});
assert.equal(el('governance-original-score').textContent,'72');
assert.equal(el('governance-adjusted-score').textContent,'57');
assert.equal(el('governance-risk-items').children.length,2);
assert.match(el('governance-risk-items').text,/扣 5 分/);
''')
    def test_ratio_input_lineage_from_backend_is_visible(self):
        self.run_ui('''
const a=item('major_shareholder_pledge');
a.evidence=[{title:'公告',date:'2026-10-20',url:'https://example.com'}];
a.ratio_inputs={numerator:30,denominator:100,unit:'股',period_end:'2026-09-30',subject:'股东甲'};
showGovernanceEvidence(a,'质押');
assert.match(el('governance-evidence-content').textContent,/分子：30/);
assert.match(el('governance-evidence-content').textContent,/分母：100/);
assert.match(el('governance-evidence-content').textContent,/2026-09-30/);
assert.match(el('governance-evidence-content').textContent,/股东甲/);
''')

    def test_partial_missing_and_critical_do_not_disappear(self):
        self.run_ui('''
const pledge=item('major_shareholder_pledge','high',false,10);
renderGovernanceRisk({original_score:72,adjusted_score:62,complete:false,items:[pledge]});
assert.equal(el('governance-adjusted-score').textContent,'—');
const cards=el('governance-risk-items').children;
assert.match(cards[0].className,/yellow/);
assert.match(cards[0].text,/高关注/);
assert.match(cards[0].text,/升级未完整评估/);
assert.match(cards[1].className,/gray/);
assert.match(cards[1].text,/未评估/);
renderGovernanceRisk({original_score:72,adjusted_score:null,complete:false,items:[item('major_shareholder_pledge','critical',false,20)]});
assert.match(el('governance-risk-items').children[0].className,/red/);
assert.match(el('governance-risk-items').children[0].text,/极高/);
assert.match(el('governance-risk-items').children[1].className,/gray/);
''')

    def test_backend_scores_and_deductions_are_not_recomputed(self):
        self.run_ui('''
for(const deduction of [0,5,10,20]) {
 const a=item('major_shareholder_pledge','watch',true,deduction); a.ratio_pct=99;
 const payload={original_score:72,adjusted_score:11,complete:true,items:[a,item('related_sales')]};
 const before=JSON.stringify(payload); renderGovernanceRisk(payload);
 assert.equal(el('governance-adjusted-score').textContent,'11');
 assert.equal(JSON.stringify(payload),before);
 assert.match(el('governance-risk-items').children[0].text,new RegExp('扣 '+deduction+' 分'));
}
renderGovernanceRisk({original_score:10,adjusted_score:0,complete:true,items:[item('major_shareholder_pledge','critical',true,20),item('related_sales','critical',true,20)]});
assert.equal(el('governance-adjusted-score').textContent,'0');
''')

    def test_evidence_safe_text_and_reset(self):
        self.run_ui('''
const a=item('major_shareholder_pledge','high',false,10);
a.title='<img src=x onerror=evil()>质押';
a.reason='<script>evil()</script>';
a.evidence.source='<svg onload=evil()>公告';
a.evidence.source_url='javascript:evil()';
a.evidence.url='https://example.com/report?q=<img>';
renderGovernanceRisk({original_score:72,adjusted_score:null,complete:false,items:[a]});
el('governance-risk-items').children[0].listeners.click();
assert.equal(el('governance-evidence-dialog').open,true);
const text=el('governance-evidence-content').textContent;
for(const expected of ['公告','2026-10-20','分子','分母','30','100','规则状态','not_triggered','未触发','<script>evil()</script>','https://example.com/report?q=<img>','非 HTTP/HTTPS']) assert.ok(text.includes(expected),expected);
assert.ok(!text.includes('javascript:'));
assert.match(text,/比例：30%/);
assert.match(text,/本项扣分：10/);
renderGovernanceRisk(undefined);
assert.equal(el('governance-evidence-dialog').open,false);
assert.equal(el('governance-evidence-content').textContent,'');
assert.equal(el('governance-original-score').textContent,'—');
assert.equal(el('governance-adjusted-score').textContent,'—');
assert.ok(el('governance-risk-items').children.every(x=>x.className.includes('gray')));
assert.ok(!el('governance-risk-items').text.includes('<img'));
''')
        source = JS.read_text()
        block = source[source.index('  function renderGovernanceRisk('):source.index('  function renderCompositeFinancialHealth(')]
        self.assertNotIn('innerHTML', block)
        self.assertNotIn('href', block)
        load = source[source.index('  async function loadAnnualFinancials('):source.index('  function apply(')]
        self.assertGreaterEqual(load.count('renderGovernanceRisk(null)'), 2)
        self.assertIn('financialRequestId !== state.financialRequestId', load)


if __name__ == '__main__':
    unittest.main()
