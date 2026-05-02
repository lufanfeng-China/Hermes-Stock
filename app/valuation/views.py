from __future__ import annotations

from .config import FINANCIAL_TEMPLATES
from .models import ViewResult


def _range_from_mid(mid: float, low_ratio: float = 0.85, high_ratio: float = 1.15) -> tuple[float, float, float]:
    return mid * low_ratio, mid, mid * high_ratio


def compute_earnings_view(data: dict[str, object], context, config: dict[str, float | None]) -> ViewResult:
    eps = data.get('eps')
    target_pe = config.get('pe')
    if eps is None or target_pe in (None, 0):
        return ViewResult('earnings', None, None, None, False, notes=['缺少 EPS 或 PE 模板参数'])
    try:
        eps = float(eps)
        target_pe = float(target_pe)
    except (TypeError, ValueError):
        return ViewResult('earnings', None, None, None, False, notes=['EPS 或 PE 参数不可解析'])
    if eps <= 0 or target_pe <= 0:
        return ViewResult('earnings', None, None, None, False, notes=['盈利视角仅适用于正 EPS'])
    low, mid, high = _range_from_mid(eps * target_pe)
    return ViewResult('earnings', low, mid, high, True, drivers=['eps', 'target_pe'], notes=['盈利视角主导参考'])


def compute_asset_view(data: dict[str, object], context, config: dict[str, float | None]) -> ViewResult:
    net_assets = data.get('net_assets')
    total_shares = data.get('total_shares')
    target_pb = config.get('pb')
    if net_assets is None or total_shares in (None, 0) or target_pb in (None, 0):
        return ViewResult('asset', None, None, None, False, notes=['缺少净资产、总股本或 PB 参数'])
    try:
        net_assets = float(net_assets)
        total_shares = float(total_shares)
        target_pb = float(target_pb)
    except (TypeError, ValueError):
        return ViewResult('asset', None, None, None, False, notes=['资产视角输入不可解析'])
    if net_assets <= 0 or total_shares <= 0 or target_pb <= 0:
        return ViewResult('asset', None, None, None, False, notes=['资产视角要求正净资产与正股本'])
    bvps = net_assets / total_shares
    low, mid, high = _range_from_mid(bvps * target_pb)
    return ViewResult('asset', low, mid, high, True, drivers=['bvps', 'target_pb'], notes=['资产视角用于净资产锚定'])


def compute_revenue_view(data: dict[str, object], context, config: dict[str, float | None]) -> ViewResult:
    if context.valuation_template_id in FINANCIAL_TEMPLATES:
        return ViewResult('revenue', None, None, None, False, notes=['金融股收入口径不可比，收入视角无效'])
    revenue = data.get('revenue')
    total_shares = data.get('total_shares')
    target_ps = config.get('ps')
    if revenue is None or total_shares in (None, 0) or target_ps in (None, 0):
        return ViewResult('revenue', None, None, None, False, notes=['缺少收入、总股本或 PS 参数'])
    try:
        revenue = float(revenue)
        total_shares = float(total_shares)
        target_ps = float(target_ps)
    except (TypeError, ValueError):
        return ViewResult('revenue', None, None, None, False, notes=['收入视角输入不可解析'])
    if revenue <= 0 or total_shares <= 0 or target_ps <= 0:
        return ViewResult('revenue', None, None, None, False, notes=['收入视角要求正收入与正股本'])
    revenue_per_share = revenue / total_shares
    low, mid, high = _range_from_mid(revenue_per_share * target_ps)
    return ViewResult('revenue', low, mid, high, True, drivers=['revenue_per_share', 'target_ps'], notes=['收入视角适用于成长性补充'])
