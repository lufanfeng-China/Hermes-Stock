"""Parent acceptance of approved high-exposure emphasis, using real renderer."""
import unittest
import tests.test_governance_risk_ui as ui_contract

class GovernanceParentAcceptance(unittest.TestCase):
    run_ui = ui_contract.GovernanceRiskUIContract.run_ui

    def test_real_backend_ratio_lineage_reaches_evidence_dialog(self):
        import json
        from app.financial.governance_risk import build_governance_risk
        from tests.test_governance_risk import evidence, AS_OF
        payload=build_governance_risk(80,evidence(90,55),AS_OF)
        self.run_ui('const data='+json.dumps(payload,ensure_ascii=False)+''';
renderGovernanceRisk(data);
el('governance-risk-items').children[0].listeners.click();
assert.match(el('governance-evidence-content').textContent,/分子：90/);
assert.match(el('governance-evidence-content').textContent,/分母：100/);
''')

    def test_backend_labels_match_frozen_policy(self):
        from app.financial.governance_risk import build_governance_risk
        from tests.test_governance_risk import evidence, AS_OF
        self.assertEqual(build_governance_risk(80,evidence(30,10),AS_OF)['items'][0]['label'],'注意')
        self.assertEqual(build_governance_risk(80,evidence(50,30),AS_OF)['items'][0]['label'],'高关注')

    def test_high_exposure_emphasis_is_visible_without_turning_red(self):
        self.run_ui('''
const a=item('major_shareholder_pledge','high',true,10); a.highly_pledged=true;
const b=item('related_sales','high',true,10); b.high_dependence=true;
renderGovernanceRisk({original_score:72,adjusted_score:52,complete:true,items:[a,b]});
const cards=el('governance-risk-items').children;
assert.match(cards[0].text,/高度质押/);
assert.match(cards[1].text,/高度依赖/);
assert.ok(cards.every(c=>c.className.includes('yellow')));
assert.ok(cards.every(c=>!c.className.includes('red')));
''')
