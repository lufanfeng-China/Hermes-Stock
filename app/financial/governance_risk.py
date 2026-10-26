"""Evidence-only current governance overlay; never alters financial scores."""
from datetime import date
from decimal import Decimal, localcontext
from pathlib import Path
import json
import math
import re

VERSION = 'governance-risk-v1'
CONFIG = {
    'major_shareholder_pledge': ('大股东质押风险', ('pledge_default', 'pledge_forced_disposal')),
    'related_sales': ('关联销售依赖风险', ('related_overdue', 'related_misstatement')),
}
LABELS = {'normal': '正常', 'watch': '注意', 'high': '高关注', 'critical': '极高风险', 'unavailable': '未评估'}
COLORS = {'normal': 'blue', 'watch': 'yellow', 'high': 'yellow', 'critical': 'red', 'unavailable': 'gray'}
DEDUCTIONS = {'normal': 0, 'watch': 5, 'high': 10, 'critical': 20, 'unavailable': None}


def load_governance_evidence(symbol, root=None) -> dict | None:
    """root is the project root, not the evidence directory. Never creates files."""
    if not isinstance(symbol, str) or re.fullmatch(r'[0-9]{6}', symbol) is None:
        return None
    try:
        project = Path(root) if root is not None else Path(__file__).resolve().parents[2]
        path = project / 'data' / 'external_risk' / 'governance_evidence' / (symbol + '.json')
        value = json.loads(path.read_text(encoding='utf-8'), parse_constant=_reject_constant)
        return value if isinstance(value, dict) and value.get('symbol', symbol) == symbol else None
    except (OSError, ValueError, TypeError, RecursionError):
        return None


def _reject_constant(value):
    raise ValueError('Non-finite JSON number: ' + value)


def _obj(value):
    return value if isinstance(value, dict) else {}


def _number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def _day(value):
    try:
        return date.fromisoformat(value) if isinstance(value, str) else value if type(value) is date else None
    except ValueError:
        return None


def _dated(value, cutoff):
    parsed = _day(value)
    return parsed is not None and cutoff is not None and parsed <= cutoff


def _sources(sources, cutoff):
    return isinstance(sources, list) and bool(sources) and all(
        isinstance(s, dict) and isinstance(s.get('url'), str) and
        re.match(r'^https?://[^/\s]+', s['url']) and isinstance(s.get('title'), str) and
        bool(s['title'].strip()) and _dated(s.get('date'), cutoff) for s in sources)


def _ratio(raw, code, cutoff, bounded=True):
    raw = _obj(raw)
    expected_scope = 'major_shareholder' if code == 'major_shareholder_pledge' else 'consolidated'
    bases = ('pledged_shares', 'held_shares') if code == 'major_shareholder_pledge' else ('related_sales', 'operating_revenue')
    n, d = raw.get('numerator'), raw.get('denominator')
    valid = (raw.get('complete') is True and raw.get('stale') is not True and
             _number(n) and _number(d) and d > 0 and (not bounded or n <= d) and
             raw.get('scope') == expected_scope and raw.get('metric') == code and
             isinstance(raw.get('subject'), str) and bool(raw['subject'].strip()) and
             raw.get('numerator_basis') == bases[0] and raw.get('denominator_basis') == bases[1] and
             _dated(raw.get('period_end'), cutoff) and _sources(raw.get('sources'), cutoff))
    valid = valid and raw.get('source_basis') not in ('overall', 'mixed')
    for prefix in ('numerator_', 'denominator_'):
        for field in ('period_end', 'subject', 'scope'):
            valid = valid and raw.get(prefix + field, raw.get(field)) == raw.get(field)
    for field in ('currency', 'unit'):
        valid = valid and isinstance(raw.get(field), str) and bool(raw[field].strip()) and (
            raw.get('numerator_' + field) == raw[field] == raw.get('denominator_' + field))
    if code == 'related_sales':
        valid = valid and raw.get('period_type') == 'annual' and str(raw.get('period_end', '')).endswith('-12-31')
        if valid:
            valid = all(_day(s['date']) >= _day(raw['period_end']) for s in raw['sources'])
    if not valid:
        return None
    # Preserve input decimal boundaries, including subnormal and large finite values.
    with localcontext() as context:
        context.prec = max(28, len(str(n)) + len(str(d)) + 4)
        return Decimal(str(n)) / Decimal(str(d)) * 100


def _rule(name, raw, code, cutoff, ratio_raw=None, pct=None):
    raw = _obj(raw)
    details = {k: raw[k] for k in ('as_of', 'subject', 'scope', 'document_kind', 'financing',
               'default_confirmed', 'disposal_started', 'control_risk_explicit', 'disposal_shares',
               'material', 'related_revenue', 'finding', 'status') if k in raw}
    scope = 'major_shareholder' if code == 'major_shareholder_pledge' else 'consolidated'
    valid = (raw.get('evaluated') is True and raw.get('complete') is True and
             raw.get('stale') is not True and type(raw.get('event_present')) is bool and
             isinstance(raw.get('subject'), str) and bool(raw['subject'].strip()) and
             raw.get('scope') == scope and _dated(raw.get('as_of'), cutoff) and
             _sources(raw.get('sources'), cutoff))
    if valid:
        valid = all(_day(s['date']) <= _day(raw['as_of']) for s in raw['sources'])
        if _obj(ratio_raw).get('subject'):
            valid = valid and raw['subject'] == ratio_raw['subject']
    triggered = False if valid else None
    if valid and raw['event_present']:
        qualifies = (name == 'pledge_default' and raw.get('document_kind') == 'announcement' and
                     raw.get('financing') == 'pledge' and raw.get('default_confirmed') is True)
        if name == 'pledge_forced_disposal':
            shares = raw.get('disposal_shares')
            qualifies = (raw.get('document_kind') == 'announcement' and raw.get('financing') == 'pledge' and
                         raw.get('disposal_started') is True and raw.get('control_risk_explicit') is True and
                         _number(shares) and shares > 0)
        if name == 'related_overdue':
            rec = _obj(raw.get('receivables'))
            metric = 'related_trade_receivables_overdue_gt_180'
            converted = dict(rec, metric='related_sales', numerator_basis='related_sales')
            overdue_pct = _ratio(converted, 'related_sales', cutoff, bounded=False)
            supported = (rec.get('metric') == metric and rec.get('numerator_basis') == metric and
                         rec.get('days_basis') == 'overdue' and rec.get('days_operator') == '>' and
                         type(rec.get('days_threshold')) is int and rec['days_threshold'] == 180 and
                         overdue_pct is not None and pct is not None and
                         all(rec.get(k) == _obj(ratio_raw).get(k) for k in
                             ('period_end', 'currency', 'unit', 'scope', 'subject', 'denominator')))
            if supported and (pct < 50 or overdue_pct < 10):
                return dict(code=name, evaluated=True, triggered=False,
                            reason='已核查，未同时达到关联销售50%和逾期应收/营收10%条件',
                            evidence=raw['sources'] + rec['sources'],
                            details=dict(details, receivables=dict(rec)))
            qualifies = supported
        if name == 'related_misstatement':
            qualifies = (raw.get('document_kind') in ('regulatory_decision', 'audit_report') and
                         raw.get('material') is True and raw.get('related_revenue') is True and
                         raw.get('finding') in ('false_revenue', 'improper_recognition'))
        if qualifies:
            resolved = (raw.get('status') == 'resolved' and _sources(raw.get('resolution_sources'), cutoff) and
                        min(_day(s['date']) for s in raw['resolution_sources']) >=
                        max(_day(s['date']) for s in raw['sources']))
            triggered = not resolved
            valid = raw.get('status') == 'unresolved' or bool(resolved)
        else:
            valid = False
            triggered = None
    reason = ('符合红色升级条件且未解除' if triggered else '已明确核查无该事件或已解除') if valid else '缺少有效证据，升级规则未完整评估'
    sources = raw.get('sources', []) if _sources(raw.get('sources'), cutoff) else []
    if _sources(raw.get('resolution_sources'), cutoff):
        sources = sources + raw['resolution_sources']
    rec = _obj(raw.get('receivables'))
    if _sources(rec.get('sources'), cutoff):
        sources = sources + rec['sources']
    if name == 'related_overdue' and valid:
        details['receivables'] = dict(rec)
    return dict(code=name, evaluated=bool(valid), triggered=triggered, reason=reason,
                evidence=sources, details=details)


def build_governance_risk(base_score, evidence=None, as_of=None) -> dict:
    cutoff = _day(as_of) if as_of is not None else date.today()
    evidence = _obj(evidence)
    items = []
    for code, (title, rules) in CONFIG.items():
        data = _obj(evidence.get(code))
        raw = _obj(data.get('ratio'))
        pct = _ratio(raw, code, cutoff)
        thresholds = (30, 50) if code == 'major_shareholder_pledge' else (10, 30)
        level = 'unavailable' if pct is None else 'normal' if pct < thresholds[0] else 'watch' if pct < thresholds[1] else 'high'
        results = [_rule(r, _obj(data.get('rules')).get(r), code, cutoff, raw, pct) for r in rules]
        if any(r['triggered'] is True for r in results):
            level = 'critical'
        complete = pct is not None and all(r['evaluated'] for r in results)
        sources = list(raw.get('sources', [])) if _sources(raw.get('sources'), cutoff) else []
        for result in results:
            for source in result.get('evidence', []):
                if source not in sources:
                    sources.append(source)
        reason = ('符合红色升级条件且未解除；' if level == 'critical' else '') + (
            '比例及红色升级规则已评估' if complete else '比例或红色升级规则证据不完整，未完整评估')
        items.append(dict(code=code, title=title, ratio_pct=float(pct) if pct is not None else None, level=level,
                          label=LABELS[level], color=COLORS[level], deduction=DEDUCTIONS[level],
                          complete=complete, reason=reason, evidence=sources,
                          details={k: raw[k] for k in ('numerator', 'denominator', 'numerator_basis',
                                   'denominator_basis', 'subject', 'scope', 'period_end', 'period_type',
                                   'currency', 'unit') if k in raw} if pct is not None else {},
                          rule_results=results,
                          highly_pledged=code == 'major_shareholder_pledge' and pct is not None and pct >= 80,
                          high_dependence=code == 'related_sales' and pct is not None and pct >= 50))
    complete = _number(base_score) and base_score <= 100 and all(i['complete'] for i in items)
    adjusted = max(0, base_score - sum(i['deduction'] for i in items)) if complete else None
    return dict(version=VERSION, original_score=base_score, adjusted_score=adjusted, complete=complete, items=items)
