"""AI report generation via Hermes subprocess."""
import json
import os
import re
import subprocess

DEFAULT_HERMES_MODEL = os.environ.get("HERMES_MODEL", "").strip()

def generate_stock_ai_report(market: str, symbol: str) -> dict[str, object]:
    history = load_recent_three_year_financial_reports(market, symbol)
    prompt = build_ai_financial_report_prompt(
        stock_name=str(history.get("stock_name") or symbol),
        market=str(history.get("market") or market),
        symbol=str(history.get("symbol") or symbol),
        reports=list(history.get("reports") or []),
        latest_report=history.get("latest_report"),
    )

    command = [
        "hermes",
        "chat",
        "-Q",
        "--ignore-rules",
        "--source",
        "tool",
    ]
    if DEFAULT_HERMES_MODEL:
        command.extend(["-m", DEFAULT_HERMES_MODEL])
    command.extend(["-q", prompt])

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or "hermes command failed").strip())

    stdout = (result.stdout or "").strip()
    match = re.search(r"(\{.*\})", stdout, re.DOTALL)
    if not match:
        raise RuntimeError("hermes output did not contain JSON")

    parsed = json.loads(match.group(1))

    def _normalize_list(value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            items = value
        else:
            items = [value]
        return [str(item).strip() for item in items if str(item).strip()]

    analysis = {
        "overall": str(parsed.get("overall") or "").strip(),
        "highlights": _normalize_list(parsed.get("highlights")),
        "risks": _normalize_list(parsed.get("risks")),
        "positive_factors": _normalize_list(parsed.get("positive_factors")),
        "negative_factors": _normalize_list(parsed.get("negative_factors")),
    }
    return {
        "ok": True,
        "market": history["market"],
        "symbol": history["symbol"],
        "stock_name": history["stock_name"],
        "report_count": len(history["reports"]),
        "latest_report": history.get("latest_report"),
        "latest_period_label": history.get("latest_period_label"),
        "reports": history["reports"],
        "analysis": analysis,
    }


def generate_sub_indicator_ai_explanation(market: str, symbol: str, sub_key: str) -> dict[str, object]:
    history = load_recent_three_year_financial_reports(market, symbol)
    score_context = load_sub_indicator_score_context(market, symbol)
    diagnostics = score_context.get("sub_indicator_diagnostics") or {}
    diagnostic = diagnostics.get(sub_key)
    if not diagnostic:
        raise ValueError(f"invalid sub_key for {market}:{symbol}: {sub_key}")

    prompt = build_sub_indicator_explanation_prompt(
        stock_name=str(score_context.get("stock_name") or history.get("stock_name") or symbol),
        market=str(score_context.get("market") or history.get("market") or market),
        symbol=str(score_context.get("symbol") or history.get("symbol") or symbol),
        sub_key=sub_key,
        diagnostic=diagnostic,
        latest_report=history.get("latest_report"),
        reports=list(history.get("reports") or []),
        ind1=str(score_context.get("ind1") or ""),
        ind2=str(score_context.get("ind2") or ""),
    )

    command = [
        "hermes",
        "chat",
        "-Q",
        "--ignore-rules",
        "--source",
        "tool",
    ]
    if DEFAULT_HERMES_MODEL:
        command.extend(["-m", DEFAULT_HERMES_MODEL])
    command.extend(["-q", prompt])

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or "hermes command failed").strip())

    stdout = (result.stdout or "").strip()
    match = re.search(r"(\{.*\})", stdout, re.DOTALL)
    if not match:
        raise RuntimeError("hermes output did not contain JSON")

    parsed = json.loads(match.group(1), strict=False)

    def _short_terminal_line(value: object, *, limit: int = 24, keep_terminal_punctuation: bool = True) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        text = re.sub(r"^(latest_report|change|attribution|impact|reports|summary|hypotheses|validation_focus)\s*[:：-]\s*", "", text, flags=re.IGNORECASE)
        if not text:
            return ""
        head_match = re.match(r"^(.*?)([；;。.!?]|$)", text)
        head = (head_match.group(1) if head_match else text).strip(" ，、;；:：")
        suffix = head_match.group(2) if head_match else ""
        if not keep_terminal_punctuation and any(sep in head for sep in ("，", ",", "、")):
            head = re.split(r"[，,、]", head, maxsplit=1)[0].strip(" ，、;；:：")
        if not keep_terminal_punctuation and "与" in head:
            head = head.split("与", 1)[0].strip(" ，、;；:：")
        if len(head) > limit:
            truncated = head[:limit].rstrip(" ，、;；:：")
            if keep_terminal_punctuation:
                split_points = [truncated.rfind(sep) for sep in ("，", ",", "、")]
                split_points = [pos for pos in split_points if pos > 0]
                if split_points:
                    truncated = truncated[:max(split_points)].rstrip(" ，、;；:：")
            head = truncated
        if keep_terminal_punctuation and suffix in {"。", "！", "？"} and head:
            return f"{head}{suffix}"
        return head

    def _normalize_list(value: object, *, limit: int = 24) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            items = value
        else:
            items = [value]
        normalized = []
        for item in items:
            text = _short_terminal_line(item, limit=limit, keep_terminal_punctuation=False)
            if text:
                normalized.append(text)
        return normalized

    def _summary_unit(sub_key_name: str) -> str:
        return {
            "roe_ex": "%",
            "net_margin": "%",
            "roe_pct": "%",
            "revenue_growth": "%",
            "profit_growth": "%",
            "ex_profit_growth": "%",
            "ar_days": "天",
            "inv_days": "天",
            "asset_turn": "次",
            "ocf_to_profit": "倍",
            "ocf_to_rev": "%",
            "debt_ratio": "%",
            "current_ratio": "倍",
            "quick_ratio": "倍",
            "ar_to_asset": "%",
            "inv_to_asset": "%",
            "goodwill_ratio": "%",
            "impair_to_rev": "%",
        }.get(sub_key_name, "")

    def _polish_summary_text(text: object, sub_key_name: str, latest_period_label: str) -> str:
        summary = _short_terminal_line(text, limit=30)
        if not summary:
            return ""
        summary = re.sub(r"(?<!\d)(\d{2})Q([1-4])", r"20\1Q\2", summary)
        if latest_period_label:
            short_period = latest_period_label[2:] if len(latest_period_label) == 6 else ""
            if short_period and short_period in summary and latest_period_label not in summary:
                summary = summary.replace(short_period, latest_period_label)
        unit = _summary_unit(sub_key_name)
        if unit:
            match_num_tail = re.search(r"(\d+(?:\.\d+)?)([。！？]?)$", summary)
            if match_num_tail:
                number = match_num_tail.group(1)
                punct = match_num_tail.group(2) or "。"
                prefix = summary[: match_num_tail.start(1)]
                summary = f"{prefix}{number}{unit}{punct}"
        elif summary[-1] not in "。！？":
            summary = f"{summary}。"
        return summary

    def _canonical_terminal_item(value: str) -> str:
        text = str(value or "").strip()
        text = re.sub(r"^(核对|查看|跟踪|补齐|对比|核查|关注)", "", text)
        return text.strip(" ，、;；:：")

    def _compress_terminal_items(items: list[str], *, limit: int = 18, max_items: int = 4) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for item in items:
            text = _short_terminal_line(item, limit=limit, keep_terminal_punctuation=False)
            canonical = _canonical_terminal_item(text)
            if not canonical or canonical in seen:
                continue
            seen.add(canonical)
            out.append(canonical)
            if len(out) >= max_items:
                break
        return out

    def _prepend_unique(items: list[str], extras: list[str], *, limit: int = 18) -> list[str]:
        return _compress_terminal_items(extras + items, limit=limit, max_items=8)

    def _apply_industry_short_templates(explanation: dict[str, object]) -> dict[str, object]:
        ind1_text = str(score_context.get("ind1") or "")
        ind2_text = str(score_context.get("ind2") or "")
        latest_period_label = str(score_context.get("latest_period") or history.get("latest_period_label") or history.get("latest_report", {}).get("period") or "")
        industry_text = f"{ind1_text}/{ind2_text}"
        industry_tags = _industry_template_tags(ind1_text, ind2_text)
        hypotheses = list(explanation.get("hypotheses") or [])
        validation_focus = list(explanation.get("validation_focus") or [])
        summary = str(explanation.get("summary") or "")

        if "nonbank_finance" in industry_tags:
            if sub_key == "free_cf":
                hypotheses = _prepend_unique(hypotheses, ["投资收付", "保费收现节奏"])
                validation_focus = _prepend_unique(validation_focus, ["保费收现", "赔付支出", "投资收付"])
                if "保险" in ind2_text and summary and "保险" not in summary:
                    summary = _short_terminal_line(f"保险资金口径下，{summary}", limit=30)
            elif sub_key in {"roe_ex", "roe_pct"}:
                hypotheses = _prepend_unique(hypotheses, ["投资收益波动", "资本消耗变化"])
                validation_focus = _prepend_unique(validation_focus, ["投资收益变动", "资本约束"])

        if "bank" in industry_tags:
            if sub_key in {"asset_turn", "revenue_growth", "profit_growth", "ex_profit_growth", "roe_ex", "roe_pct"}:
                hypotheses = _prepend_unique(hypotheses, ["息差", "资产扩张"])
                validation_focus = _prepend_unique(validation_focus, ["存贷", "净息差"])
                if summary and "银行" not in summary:
                    summary = _short_terminal_line(f"银行口径下，{summary}", limit=30)
            elif sub_key in {"current_ratio", "quick_ratio", "debt_ratio"}:
                hypotheses = _prepend_unique(hypotheses, ["负债成本", "资产久期"])
                validation_focus = _prepend_unique(validation_focus, ["负债久期", "资本充足率"])

        if "industrial_metal" in industry_tags:
            if sub_key in {"inv_to_asset", "inv_days"}:
                hypotheses = _prepend_unique(hypotheses, ["金属价格", "库存周期"])
                validation_focus = _prepend_unique(validation_focus, ["产销节奏", "库存附注"])
                if "工业金属" in ind2_text and summary and "工业金属" not in summary:
                    summary = _short_terminal_line(f"工业金属链条里，{summary}", limit=30)
            elif sub_key in {"revenue_growth", "profit_growth", "ex_profit_growth"}:
                hypotheses = _prepend_unique(hypotheses, ["金属价格波动", "加工费变化"])
                validation_focus = _prepend_unique(validation_focus, ["量价拆分", "产销节奏"])

        if "consumer" in industry_tags:
            if sub_key in {"revenue_growth", "profit_growth", "ex_profit_growth", "net_margin"}:
                hypotheses = _prepend_unique(hypotheses, ["渠道动销", "提价节奏"])
                validation_focus = _prepend_unique(validation_focus, ["终端动销", "渠道库存"])
                if summary and not any(token in summary for token in ("消费", "白酒", "食品饮料")):
                    summary = _short_terminal_line(f"消费品口径下，{summary}", limit=30)

        if "pharma" in industry_tags:
            if sub_key in {"revenue_growth", "profit_growth", "ex_profit_growth", "roe_ex", "net_margin"}:
                hypotheses = _prepend_unique(hypotheses, ["集采", "产品放量"])
                validation_focus = _prepend_unique(validation_focus, ["院内销售", "研发投入"])
                if summary and "医药" not in summary:
                    summary = _short_terminal_line(f"医药口径下，{summary}", limit=30)

        if "tech_media" in industry_tags:
            if sub_key in {"inv_days", "inv_to_asset", "revenue_growth", "profit_growth", "ex_profit_growth"}:
                hypotheses = _prepend_unique(hypotheses, ["景气周期", "稼动率"])
                validation_focus = _prepend_unique(validation_focus, ["订单能见度", "库存周转"])
                if summary and "半导体" not in summary and "电子" not in summary:
                    summary = _short_terminal_line(f"电子链条里，{summary}", limit=30)
            elif sub_key in {"asset_turn", "ar_days"}:
                hypotheses = _prepend_unique(hypotheses, ["客户订单", "产品周期"])
                validation_focus = _prepend_unique(validation_focus, ["订单能见度", "回款周期"])

        if "cyclical_manufacturing" in industry_tags:
            if sub_key in {"revenue_growth", "profit_growth", "ex_profit_growth", "asset_turn", "ar_days"}:
                hypotheses = _prepend_unique(hypotheses, ["订单节奏", "产能利用率"])
                validation_focus = _prepend_unique(validation_focus, ["在手订单", "开工率"])
                if summary and "机械" not in summary and "制造" not in summary:
                    summary = _short_terminal_line(f"周期制造口径下，{summary}", limit=30)
            elif sub_key in {"inv_days", "inv_to_asset"}:
                hypotheses = _prepend_unique(hypotheses, ["补库节奏", "排产变化"])
                validation_focus = _prepend_unique(validation_focus, ["产销节奏", "库存周转"])

        if "utilities_env" in industry_tags:
            hypotheses = _prepend_unique(hypotheses, ["成本传导", "价格机制"])
            validation_focus = _prepend_unique(validation_focus, ["电价气价", "燃料成本"])
            if summary and "公用" not in summary and "环保" not in summary:
                summary = _short_terminal_line(f"公用环保口径下，{summary}", limit=30)

        if "materials_resources" in industry_tags:
            if sub_key not in {"inv_to_asset", "inv_days", "revenue_growth", "profit_growth", "ex_profit_growth"}:
                hypotheses = _prepend_unique(hypotheses, ["价格周期", "成本价差"])
                validation_focus = _prepend_unique(validation_focus, ["量价拆分", "库存附注"])

        if "agriculture" in industry_tags:
            hypotheses = _prepend_unique(hypotheses, ["养殖周期", "农产品价格"])
            validation_focus = _prepend_unique(validation_focus, ["出栏节奏", "原料成本"])
            if summary and "农林牧渔" not in summary:
                summary = _short_terminal_line(f"农业口径下，{summary}", limit=30)

        if "real_estate" in industry_tags:
            hypotheses = _prepend_unique(hypotheses, ["去化", "拿地节奏"])
            validation_focus = _prepend_unique(validation_focus, ["销售回款", "土储结构"])
            if summary and "地产" not in summary:
                summary = _short_terminal_line(f"地产口径下，{summary}", limit=30)

        if "composite" in industry_tags:
            hypotheses = _prepend_unique(hypotheses, ["业务结构", "资产处置"])
            validation_focus = _prepend_unique(validation_focus, ["分部口径", "非经常损益"])
            if summary and "综合" not in summary:
                summary = _short_terminal_line(f"综合口径下，{summary}", limit=30)

        explanation["summary"] = _polish_summary_text(summary, sub_key, latest_period_label)
        explanation["hypotheses"] = _compress_terminal_items(hypotheses, limit=18, max_items=4)
        explanation["validation_focus"] = _compress_terminal_items(validation_focus, limit=18, max_items=4)
        return explanation

    confidence = str(parsed.get("confidence") or "").strip().lower()
    if confidence not in {"low", "medium", "high"}:
        confidence = "medium"

    explanation = {
        "status": "ready",
        "summary": _short_terminal_line(parsed.get("summary"), limit=30),
        "hypotheses": _normalize_list(parsed.get("hypotheses"), limit=18),
        "validation_focus": _normalize_list(parsed.get("validation_focus"), limit=18),
        "confidence": confidence,
    }
    explanation = _apply_industry_short_templates(explanation)

    return {
        "ok": True,
        "market": str(score_context.get("market") or history.get("market") or market),
        "symbol": str(score_context.get("symbol") or history.get("symbol") or symbol),
        "stock_name": score_context.get("stock_name") or history.get("stock_name") or symbol,
        "sub_key": sub_key,
        "indicator_name": str(diagnostic.get("indicator_name") or sub_key),
        "explanation": explanation,
    }


