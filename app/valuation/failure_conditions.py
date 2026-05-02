from __future__ import annotations


def build_failure_conditions(data: dict[str, object], template_id: str) -> list[str]:
    conditions: list[str] = []
    if template_id in {'bank', 'nonbank_finance'}:
        conditions.append('若监管政策或资本约束显著变化，则当前资产视角锚定失效。')
    else:
        conditions.append('若未来两个季度利润增速明显失速，则盈利视角锚定失效。')
    if data.get('debt_ratio') is not None:
        conditions.append('若资产负债率继续显著上升，则资产与盈利视角需同步下修。')
    conditions.append('若公司发生重大资产重组或商业模式突变，则当前模板映射失效。')
    return conditions[:3]
