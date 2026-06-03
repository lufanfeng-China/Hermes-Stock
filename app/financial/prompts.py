"""AI prompt builders for financial analysis."""
import json

def build_ai_financial_report_prompt(
    *,
    stock_name: str,
    market: str,
    symbol: str,
    reports: list[dict[str, object]],
    latest_report: dict[str, object] | None = None,
) -> str:
    latest = latest_report or (reports[-1] if reports else None)
    report_blob = json.dumps(reports, ensure_ascii=False, indent=2)
    latest_blob = json.dumps(latest, ensure_ascii=False, indent=2)
    return (
        f"你是一名A股财报分析师。请基于 {stock_name}（{market}:{symbol}）最近3年财报数据，"
        "输出严格 JSON，不要输出任何额外说明。\n"
        "解读逻辑必须以最新一期财报为主，优先与上年同期比较；只有在完成上年同期比较后，才把更早历史作为辅助验证，不要把历史数据当成主结论。\n"
        "请重点覆盖：总体评价、财报亮点、风险警示、加分项、减分项。\n"
        "JSON 字段必须且只能包含：overall, highlights, risks, positive_factors, negative_factors。\n"
        "其中 overall 为字符串，其余字段为字符串数组；内容使用简洁中文。\n"
        "请明确关注最新一期的营收同比、净利润同比、扣非同比，以及少量质量指标如扣非ROE、资产负债率、流动比率。\n"
        "若最新一期是季度报告，请先对比上年同期（例如 2026Q1 先比 2025Q1），再参考更早同季度或前后报告期；若最新一期是年报，也要优先与上年同期年报比较。\n"
        "你会收到 latest_report 和 reports 两部分：latest_report 是主分析对象，reports 是最近3年完整报告期时间线（按时间顺序）。\n"
        f"latest_report:\n{latest_blob}\n"
        "reports:\n"
        f"{report_blob}\n"
        "请返回 JSON。"
    )



def load_sub_indicator_score_context(market: str, symbol: str) -> dict[str, object]:
    search_index = importlib.import_module("app.search.index")

    market = str(market or "").strip().lower()
    symbol = str(symbol or "").strip()
    if market not in {"sh", "sz", "bj"}:
        raise ValueError("market must be sh, sz or bj")
    if not symbol.isdigit() or len(symbol) != 6:
        raise ValueError("symbol must be a 6-digit code")

    return search_index.compute_stock_score(market, symbol)


def build_sub_indicator_explanation_prompt(

def build_sub_indicator_explanation_prompt(
    *,
    stock_name: str,
    market: str,
    symbol: str,
    sub_key: str,
    diagnostic: dict[str, object],
    latest_report: dict[str, object] | None,
    reports: list[dict[str, object]],
    ind1: str = "",
    ind2: str = "",
) -> str:
    indicator_name = str(diagnostic.get("indicator_name") or sub_key).strip() or sub_key
    diagnostic_blob = json.dumps(diagnostic, ensure_ascii=False, indent=2)
    latest_blob = json.dumps(latest_report or {}, ensure_ascii=False, indent=2)
    report_blob = json.dumps(reports, ensure_ascii=False, indent=2)
    industry_context = " / ".join([part for part in [str(ind1 or "").strip(), str(ind2 or "").strip()] if part]) or "未提供行业标签"
    return (
        f"你是一名A股财报分析师。请只解释 {stock_name}（{market}:{symbol}）的单个财务指标 {indicator_name}（sub_key={sub_key}），"
        "输出严格 JSON，不要输出任何额外说明。\n"
        "默认不要分析其他指标，不要扩展到公司整体结论，只围绕这一个指标的变化、归因、影响、可能原因与验证重点作答。\n"
        "分析顺序必须先看最新一期 latest_report，再优先对比上年同期（同季度对同季度、年报对上年年报），再把 reports 里的更早历史作为辅助验证。\n"
        "请明确使用 change、attribution、impact、latest_report、reports 这些上下文，并把最新一期放在最前面。\n"
        "请特别关注：变化、归因、影响、可能原因、验证重点。\n"
        "输出必须是终端风格短句：一句结论 + 若干条原因/验证短句，不要写成长段分析。\n"
        "不要照抄 latest_report、change、attribution、impact、reports 这些字段名；直接写中文结论。\n"
        "单条尽量不超过 24 个汉字；优先使用动宾短句、判断短句、研究终端口吻。\n"
        "JSON 字段必须且只能包含：summary, hypotheses, validation_focus, confidence。\n"
        "其中 summary 为字符串；hypotheses 与 validation_focus 为字符串数组；confidence 为字符串，只能使用 low / medium / high。\n"
        "如果现有证据不足，请在 hypotheses 和 validation_focus 中直接说明要核查的公告、附注或业务口径；不要编造未提供的数据。\n"
        f"行业上下文: {industry_context}\n"
        "若行业标签显示保险/非银金融，请优先使用保费收现、赔付支出、投资收付、负债久期等行业表达。\n"
        "若行业标签显示工业金属，请优先使用金属价格、库存周期、产销节奏、在途库存等行业表达。\n"
        "latest_report:\n"
        f"{latest_blob}\n"
        "reports:\n"
        f"{report_blob}\n"
        "sub_indicator_diagnostic:\n"
        f"{diagnostic_blob}\n"
        "请返回 JSON。"
    )


