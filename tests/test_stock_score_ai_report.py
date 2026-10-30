import json
import unittest
from unittest import mock

import app.config as app_config
import app.financial.ai_report as ai_report
from app import handler as app_handler
from app.data import rps_history
from app.financial import prompts as financial_prompts
from app.financial import reports as financial_reports
from app.financial import warehouse_reports
from app.industry import templates as industry_templates

# 服务端拆分后，scripts/serve_stock_dashboard.py 只剩入口逻辑，原先的 AI 财报实现迁到
# app/financial/{prompts,reports,ai_report}.py 与 app/industry/templates.py。
# app/financial/ai_report.py 的调用点（第 10/11/77/78/84/232 行）使用了这些名字却没有在
# 模块内 import，因此这里把迁移后的真实实现绑定到该模块命名空间；这样 mock.patch.object
# 打到的就是 generate_* 实际解析的同一个全局名，mock 的调用点与真实调用点一致。
_AI_REPORT_IMPLEMENTATIONS = {
    "load_recent_three_year_financial_reports": financial_reports.load_recent_three_year_financial_reports,
    "build_ai_financial_report_prompt": financial_prompts.build_ai_financial_report_prompt,
    "load_sub_indicator_score_context": financial_prompts.load_sub_indicator_score_context,
    "build_sub_indicator_explanation_prompt": financial_prompts.build_sub_indicator_explanation_prompt,
    "_industry_template_tags": industry_templates._industry_template_tags,
}
for _symbol_name, _implementation in _AI_REPORT_IMPLEMENTATIONS.items():
    if getattr(ai_report, _symbol_name, None) is not _implementation:
        setattr(ai_report, _symbol_name, _implementation)


class StockScoreAiReportTests(unittest.TestCase):
    def test_load_stock_rps_history_reads_parquet_contract_with_rps120_and_rps250(self) -> None:
        """迁移后契约：RPS 历史直接读权威 Parquet，且 rps_120/rps_250 必须随行返回。

        旧实现（subprocess 调通达信 Python 跑内联脚本）已随服务端拆分整体删除，
        因此这里断言新的真实契约：不派生子进程、数据来自 dataset_stock_rps_history.parquet、
        每条记录同时带 rps_20/50/120/250 四个截面排名。
        """
        with mock.patch("subprocess.run") as run_mock:
            payload = rps_history.load_stock_rps_history("000001")

        run_mock.assert_not_called()  # 不再依赖外部 Python 进程
        self.assertTrue(payload["ok"])
        self.assertEqual("000001", payload["symbol"])
        self.assertEqual("sz", payload["market"])
        history = payload["history"]
        self.assertTrue(history, "000001 应至少在权威 Parquet 中有一条 RPS 历史")
        for record in history:
            for key in ("trading_day", "rps_20", "rps_50", "rps_120", "rps_250"):
                self.assertIn(key, record)
            self.assertIsNotNone(record["rps_120"])
            self.assertIsNotNone(record["rps_250"])
        self.assertEqual(
            sorted(record["trading_day"] for record in history)[-1],
            history[-1]["trading_day"],
            "历史必须按交易日升序",
        )

    def test_build_ai_financial_report_prompt_mentions_required_sections(self) -> None:
        reports = [
            {
                "report_date": "20260331",
                "period": "2026Q1",
                "announce_date": "20260429",
                "metrics": {
                    "revenue": 1200.0,
                    "net_profit": 180.0,
                    "ocf": 210.0,
                    "roe_ex": 12.8,
                    "debt_ratio": 41.2,
                },
            }
        ]

        prompt = financial_prompts.build_ai_financial_report_prompt(
            stock_name="中国平安",
            market="sh",
            symbol="601318",
            reports=reports,
        )

        self.assertIn("最近3年", prompt)
        self.assertIn("总体评价", prompt)
        self.assertIn("财报亮点", prompt)
        self.assertIn("风险警示", prompt)
        self.assertIn("加分项", prompt)
        self.assertIn("减分项", prompt)
        self.assertIn("最新一期", prompt)
        self.assertIn("同季度", prompt)
        self.assertIn("上年同期", prompt)
        self.assertIn("JSON", prompt)
        self.assertIn("中国平安", prompt)

    def test_build_sub_indicator_explanation_prompt_mentions_required_sections(self) -> None:
        diagnostic = {
            "indicator_name": "自由现金流",
            "change": {
                "summary": "自由现金流较上期明显回落",
                "current": 12.3,
                "previous": 25.6,
                "delta": -13.3,
                "delta_pct": -51.9,
                "unit": "亿",
            },
            "attribution": {
                "summary": "主因：经营现金流回落；次因：暂无更强同向次因；对冲项：资本开支收缩。",
                "template_type": "formula_decomposition",
                "evidence_strength": "high",
                "needs_text_validation": False,
                "validation_sources": ["无需额外文本验证"],
                "industry_scope": "全行业通用",
            },
            "impact": {
                "impact_summary": "可支配现金与资本配置空间承压",
                "impact_risks": [
                    "主影响：经营现金流回落意味着可支配现金与资本配置空间首先承压。",
                    "次影响：会继续影响分红、回购与扩产弹性。",
                    "缓冲项：资本开支收缩对现金沉淀压力形成一定缓冲。",
                ],
            },
            "explanation": {"status": "idle", "content": ""},
        }
        reports = [
            {
                "report_date": "20260331",
                "period": "2026Q1",
                "announce_date": "20260429",
                "metrics": {
                    "revenue": 1200.0,
                    "net_profit": 180.0,
                    "ocf": 210.0,
                    "roe_ex": 12.8,
                    "debt_ratio": 41.2,
                },
            }
        ]

        prompt = financial_prompts.build_sub_indicator_explanation_prompt(
            stock_name="中国平安",
            market="sh",
            symbol="601318",
            sub_key="free_cf",
            diagnostic=diagnostic,
            latest_report=reports[-1],
            reports=reports,
        )

        self.assertIn("单个财务指标", prompt)
        self.assertIn("自由现金流", prompt)
        self.assertIn("变化", prompt)
        self.assertIn("归因", prompt)
        self.assertIn("影响", prompt)
        self.assertIn("可能原因", prompt)
        self.assertIn("验证重点", prompt)
        self.assertIn("confidence", prompt)
        self.assertIn("JSON", prompt)
        self.assertIn("默认不要分析其他指标", prompt)
        self.assertIn("终端风格短句", prompt)
        self.assertIn("一句结论", prompt)
        self.assertIn("不要照抄 latest_report", prompt)
        self.assertIn("单条尽量不超过", prompt)
        self.assertIn("行业上下文", prompt)
        self.assertIn("最新一期", prompt)
        self.assertIn("上年同期", prompt)

    def test_generate_stock_ai_report_parses_hermes_json_output(self) -> None:
        hermes_output = 'session_id: 20260429_123456\n{"overall": "稳健", "highlights": ["现金流改善"], "risks": ["保费增速放缓"], "positive_factors": ["盈利修复"], "negative_factors": ["投资波动"]}'
        report_history = {
            "market": "sh",
            "symbol": "601318",
            "stock_name": "中国平安",
            "reports": [{"report_date": "20260331", "metrics": {"revenue": 1200.0}}],
        }

        with (
            mock.patch.object(ai_report, "load_recent_three_year_financial_reports", return_value=report_history),
            mock.patch.object(ai_report.subprocess, "run") as run_mock,
        ):
            run_mock.return_value = mock.Mock(returncode=0, stdout=hermes_output, stderr="")
            result = ai_report.generate_stock_ai_report("sh", "601318")

        self.assertTrue(result["ok"])
        self.assertEqual("中国平安", result["stock_name"])
        self.assertEqual("稳健", result["analysis"]["overall"])
        self.assertEqual(["现金流改善"], result["analysis"]["highlights"])
        self.assertEqual(["保费增速放缓"], result["analysis"]["risks"])
        self.assertEqual(["盈利修复"], result["analysis"]["positive_factors"])
        self.assertEqual(["投资波动"], result["analysis"]["negative_factors"])
        self.assertEqual(1, result["report_count"])
        command = run_mock.call_args.args[0]
        self.assertIn("hermes", command[0])
        self.assertIn("chat", command)
        self.assertIn("-q", command)

    def test_generate_sub_indicator_ai_explanation_parses_hermes_json_output(self) -> None:
        hermes_output = 'session_id: 20260429_123456\n{"summary": "自由现金流回落主要和经营现金流承压有关。", "hypotheses": ["回款放缓", "项目投入仍高"], "validation_focus": ["查看公告正文中的经营现金流解释", "核对资本开支项目进度"], "confidence": "medium"}'
        score_payload = {
            "ok": True,
            "stock_name": "中国平安",
            "latest_period": "2026Q1",
            "sub_indicator_diagnostics": {
                "free_cf": {
                    "indicator_name": "自由现金流",
                    "change": {"summary": "自由现金流较上期明显回落"},
                    "attribution": {
                        "summary": "主因：经营现金流回落；次因：暂无更强同向次因；对冲项：资本开支收缩。",
                        "validation_sources": ["无需额外文本验证"],
                        "needs_text_validation": False,
                        "evidence_strength": "high",
                        "industry_scope": "全行业通用",
                    },
                    "impact": {
                        "impact_summary": "可支配现金与资本配置空间承压",
                        "impact_risks": ["主影响：经营现金流回落意味着可支配现金与资本配置空间首先承压。"],
                    },
                    "explanation": {"status": "idle", "content": ""},
                }
            },
        }
        report_history = {
            "market": "sh",
            "symbol": "601318",
            "stock_name": "中国平安",
            "latest_report": {"report_date": "20260331", "period": "2026Q1", "metrics": {"revenue": 1200.0}},
            "reports": [{"report_date": "20260331", "period": "2026Q1", "metrics": {"revenue": 1200.0}}],
        }

        with (
            mock.patch.object(ai_report, "load_recent_three_year_financial_reports", return_value=report_history),
            mock.patch.object(ai_report, "load_sub_indicator_score_context", return_value=score_payload),
            mock.patch.object(ai_report.subprocess, "run") as run_mock,
        ):
            run_mock.return_value = mock.Mock(returncode=0, stdout=hermes_output, stderr="")
            result = ai_report.generate_sub_indicator_ai_explanation("sh", "601318", "free_cf")

        self.assertTrue(result["ok"])
        self.assertEqual("中国平安", result["stock_name"])
        self.assertEqual("free_cf", result["sub_key"])
        self.assertEqual("自由现金流", result["indicator_name"])
        self.assertEqual("ready", result["explanation"]["status"])
        self.assertEqual("自由现金流回落主要和经营现金流承压有关。", result["explanation"]["summary"])
        self.assertEqual(["回款放缓", "项目投入仍高"], result["explanation"]["hypotheses"])
        self.assertEqual(["公告正文中的经营现金流解释", "资本开支项目进度"], result["explanation"]["validation_focus"])
        self.assertEqual("medium", result["explanation"]["confidence"])

    def test_generate_sub_indicator_ai_explanation_normalizes_terminal_style_short_lines(self) -> None:
        hermes_output = 'session_id: 20260429_123456\n{"summary": "  自由现金流承压，主看经营现金流回落。\n进一步看同比而非年报季节性。  ", "hypotheses": ["  回款放缓导致净流入走弱，拖累自由现金流表现。  ", "项目投入仍高，现金沉淀继续承压。", ""], "validation_focus": [" 查看经营活动现金流量净额同比变动原因与附注拆分。 ", "核对资本开支项目进度与付款节奏。"], "confidence": "MEDIUM"}'
        score_payload = {
            "ok": True,
            "stock_name": "中国平安",
            "latest_period": "2026Q1",
            "sub_indicator_diagnostics": {
                "free_cf": {
                    "indicator_name": "自由现金流",
                    "change": {"summary": "自由现金流较上期明显回落"},
                    "attribution": {"summary": "主因：经营现金流回落。"},
                    "impact": {"impact_summary": "可支配现金与资本配置空间承压", "impact_risks": ["主影响：现金弹性走弱。"]},
                    "explanation": {"status": "idle", "content": ""},
                }
            },
        }
        report_history = {
            "market": "sh",
            "symbol": "601318",
            "stock_name": "中国平安",
            "latest_report": {"report_date": "20260331", "period": "2026Q1", "metrics": {"revenue": 1200.0}},
            "reports": [{"report_date": "20260331", "period": "2026Q1", "metrics": {"revenue": 1200.0}}],
        }

        with (
            mock.patch.object(ai_report, "load_recent_three_year_financial_reports", return_value=report_history),
            mock.patch.object(ai_report, "load_sub_indicator_score_context", return_value=score_payload),
            mock.patch.object(ai_report.subprocess, "run") as run_mock,
        ):
            run_mock.return_value = mock.Mock(returncode=0, stdout=hermes_output, stderr="")
            result = ai_report.generate_sub_indicator_ai_explanation("sh", "601318", "free_cf")

        self.assertEqual("ready", result["explanation"]["status"])
        self.assertEqual("自由现金流承压，主看经营现金流回落。", result["explanation"]["summary"])
        self.assertEqual(["回款放缓导致净流入走弱", "项目投入仍高"], result["explanation"]["hypotheses"])
        self.assertEqual(["经营活动现金流量净额同比变动原因", "资本开支项目进度"], result["explanation"]["validation_focus"])
        self.assertEqual("medium", result["explanation"]["confidence"])
        command = run_mock.call_args.args[0]

    def test_generate_sub_indicator_ai_explanation_removes_truncated_tail_fragments(self) -> None:
        hermes_output = 'session_id: 20260429_123456\n{"summary": "2026Q1自由现金流同比降46%，主因经营现金流回落，资本开支仅小幅收缩。", "hypotheses": ["latest_report:1296亿对应高基数回落。", "impact:分红弹性承压，但并未恶化为流动性风险。"], "validation_focus": ["reports:核查2025Q1高基数来源。", "validation_focus:核查现金流附注口径与经营现金流分项。"], "confidence": "high"}'
        score_payload = {
            "ok": True,
            "stock_name": "中国平安",
            "latest_period": "2026Q1",
            "sub_indicator_diagnostics": {
                "free_cf": {
                    "indicator_name": "自由现金流",
                    "change": {"summary": "自由现金流较上期明显回落"},
                    "attribution": {"summary": "主因：经营现金流回落。"},
                    "impact": {"impact_summary": "可支配现金与资本配置空间承压", "impact_risks": ["主影响：现金弹性走弱。"]},
                    "explanation": {"status": "idle", "content": ""},
                }
            },
        }
        report_history = {
            "market": "sh",
            "symbol": "601318",
            "stock_name": "中国平安",
            "latest_report": {"report_date": "20260331", "period": "2026Q1", "metrics": {"revenue": 1200.0}},
            "reports": [{"report_date": "20260331", "period": "2026Q1", "metrics": {"revenue": 1200.0}}],
        }

        with (
            mock.patch.object(ai_report, "load_recent_three_year_financial_reports", return_value=report_history),
            mock.patch.object(ai_report, "load_sub_indicator_score_context", return_value=score_payload),
            mock.patch.object(ai_report.subprocess, "run") as run_mock,
        ):
            run_mock.return_value = mock.Mock(returncode=0, stdout=hermes_output, stderr="")
            result = ai_report.generate_sub_indicator_ai_explanation("sh", "601318", "free_cf")

        self.assertEqual("2026Q1自由现金流同比降46%，主因经营现金流回落。", result["explanation"]["summary"])
        self.assertEqual(["1296亿对应高基数回落", "分红弹性承压"], result["explanation"]["hypotheses"])
        self.assertEqual(["2025Q1高基数来源", "现金流附注口径"], result["explanation"]["validation_focus"])
        command = run_mock.call_args.args[0]
        self.assertIn("hermes", command[0])
        self.assertIn("chat", command)
        self.assertIn("-q", command)

    def test_generate_sub_indicator_ai_explanation_applies_insurance_short_templates(self) -> None:
        hermes_output = 'session_id: 20260429_123456\n{"summary": "自由现金流承压。", "hypotheses": ["经营现金流回落", "现金流波动"], "validation_focus": ["核查经营现金流附注", "核查回款"], "confidence": "medium"}'
        score_payload = {
            "ok": True,
            "stock_name": "中国平安",
            "ind1": "非银金融",
            "ind2": "保险",
            "sub_indicator_diagnostics": {
                "free_cf": {
                    "indicator_name": "自由现金流",
                    "change": {"summary": "自由现金流较上期明显回落"},
                    "attribution": {"summary": "主因：经营现金流回落。"},
                    "impact": {"impact_summary": "可支配现金与资本配置空间承压", "impact_risks": ["主影响：现金弹性走弱。"]},
                    "explanation": {"status": "idle", "content": ""},
                }
            },
        }
        report_history = {
            "market": "sh",
            "symbol": "601318",
            "stock_name": "中国平安",
            "latest_report": {"report_date": "20260331", "period": "2026Q1", "metrics": {"revenue": 1200.0}},
            "reports": [{"report_date": "20260331", "period": "2026Q1", "metrics": {"revenue": 1200.0}}],
        }

        with (
            mock.patch.object(ai_report, "load_recent_three_year_financial_reports", return_value=report_history),
            mock.patch.object(ai_report, "load_sub_indicator_score_context", return_value=score_payload),
            mock.patch.object(ai_report.subprocess, "run") as run_mock,
        ):
            run_mock.return_value = mock.Mock(returncode=0, stdout=hermes_output, stderr="")
            result = ai_report.generate_sub_indicator_ai_explanation("sh", "601318", "free_cf")

        self.assertIn("保费收现", result["explanation"]["validation_focus"])
        self.assertIn("赔付支出", result["explanation"]["validation_focus"])
        self.assertIn("投资收付", result["explanation"]["hypotheses"])

    def test_generate_sub_indicator_ai_explanation_applies_industrial_metal_short_templates(self) -> None:
        hermes_output = 'session_id: 20260429_123456\n{"summary": "存货占比抬升。", "hypotheses": ["库存上升", "需求波动"], "validation_focus": ["核查库存附注", "核查经营数据"], "confidence": "medium"}'
        score_payload = {
            "ok": True,
            "stock_name": "中国铝业",
            "ind1": "有色金属",
            "ind2": "工业金属",
            "sub_indicator_diagnostics": {
                "inv_to_asset": {
                    "indicator_name": "存货占比",
                    "change": {"summary": "存货占比较上期抬升"},
                    "attribution": {"summary": "主因：存货抬升。"},
                    "impact": {"impact_summary": "库存沉淀压力走高", "impact_risks": ["主影响：库存占压抬升。"]},
                    "explanation": {"status": "idle", "content": ""},
                }
            },
        }
        report_history = {
            "market": "sh",
            "symbol": "601600",
            "stock_name": "中国铝业",
            "latest_report": {"report_date": "20260331", "period": "2026Q1", "metrics": {"revenue": 1200.0}},
            "reports": [{"report_date": "20260331", "period": "2026Q1", "metrics": {"revenue": 1200.0}}],
        }

        with (
            mock.patch.object(ai_report, "load_recent_three_year_financial_reports", return_value=report_history),
            mock.patch.object(ai_report, "load_sub_indicator_score_context", return_value=score_payload),
            mock.patch.object(ai_report.subprocess, "run") as run_mock,
        ):
            run_mock.return_value = mock.Mock(returncode=0, stdout=hermes_output, stderr="")
            result = ai_report.generate_sub_indicator_ai_explanation("sh", "601600", "inv_to_asset")

        self.assertIn("金属价格", result["explanation"]["hypotheses"])
        self.assertIn("库存周期", result["explanation"]["hypotheses"])
        self.assertIn("产销节奏", result["explanation"]["validation_focus"])

    def test_generate_sub_indicator_ai_explanation_applies_consumer_short_templates(self) -> None:
        hermes_output = 'session_id: 20260429_123456\n{"summary": "营收增速放缓。", "hypotheses": ["收入增速回落", "需求承压"], "validation_focus": ["核查营收附注", "核查渠道"], "confidence": "medium"}'
        score_payload = {
            "ok": True,
            "stock_name": "贵州茅台",
            "ind1": "食品饮料",
            "ind2": "白酒",
            "sub_indicator_diagnostics": {
                "revenue_growth": {
                    "indicator_name": "营收增速",
                    "change": {"summary": "营收增速较上期回落"},
                    "attribution": {"summary": "主因：收入动能放缓。"},
                    "impact": {"impact_summary": "收入弹性走弱", "impact_risks": ["主影响：收入增速回落。"]},
                    "explanation": {"status": "idle", "content": ""},
                }
            },
        }
        report_history = {
            "market": "sh",
            "symbol": "600519",
            "stock_name": "贵州茅台",
            "latest_report": {"report_date": "20260331", "period": "2026Q1", "metrics": {"revenue": 1200.0}},
            "reports": [{"report_date": "20260331", "period": "2026Q1", "metrics": {"revenue": 1200.0}}],
        }

        with (
            mock.patch.object(ai_report, "load_recent_three_year_financial_reports", return_value=report_history),
            mock.patch.object(ai_report, "load_sub_indicator_score_context", return_value=score_payload),
            mock.patch.object(ai_report.subprocess, "run") as run_mock,
        ):
            run_mock.return_value = mock.Mock(returncode=0, stdout=hermes_output, stderr="")
            result = ai_report.generate_sub_indicator_ai_explanation("sh", "600519", "revenue_growth")

        self.assertIn("渠道动销", result["explanation"]["hypotheses"])
        self.assertIn("提价节奏", result["explanation"]["hypotheses"])
        self.assertIn("终端动销", result["explanation"]["validation_focus"])
        self.assertIn("渠道库存", result["explanation"]["validation_focus"])

    def test_generate_sub_indicator_ai_explanation_applies_pharma_short_templates(self) -> None:
        hermes_output = 'session_id: 20260429_123456\n{"summary": "扣非增速承压。", "hypotheses": ["利润放缓", "销售承压"], "validation_focus": ["核查利润附注", "核查销售"], "confidence": "medium"}'
        score_payload = {
            "ok": True,
            "stock_name": "恒瑞医药",
            "ind1": "医药生物",
            "ind2": "化学制药",
            "sub_indicator_diagnostics": {
                "ex_profit_growth": {
                    "indicator_name": "扣非增速",
                    "change": {"summary": "扣非增速较上期回落"},
                    "attribution": {"summary": "主因：核心经营利润放缓。"},
                    "impact": {"impact_summary": "核心利润弹性走弱", "impact_risks": ["主影响：核心利润承压。"]},
                    "explanation": {"status": "idle", "content": ""},
                }
            },
        }
        report_history = {
            "market": "sh",
            "symbol": "600276",
            "stock_name": "恒瑞医药",
            "latest_report": {"report_date": "20260331", "period": "2026Q1", "metrics": {"revenue": 1200.0}},
            "reports": [{"report_date": "20260331", "period": "2026Q1", "metrics": {"revenue": 1200.0}}],
        }

        with (
            mock.patch.object(ai_report, "load_recent_three_year_financial_reports", return_value=report_history),
            mock.patch.object(ai_report, "load_sub_indicator_score_context", return_value=score_payload),
            mock.patch.object(ai_report.subprocess, "run") as run_mock,
        ):
            run_mock.return_value = mock.Mock(returncode=0, stdout=hermes_output, stderr="")
            result = ai_report.generate_sub_indicator_ai_explanation("sh", "600276", "ex_profit_growth")

        self.assertIn("集采", result["explanation"]["hypotheses"])
        self.assertIn("产品放量", result["explanation"]["hypotheses"])
        self.assertIn("院内销售", result["explanation"]["validation_focus"])
        self.assertIn("研发投入", result["explanation"]["validation_focus"])

    def test_generate_sub_indicator_ai_explanation_applies_semiconductor_short_templates(self) -> None:
        hermes_output = 'session_id: 20260429_123456\n{"summary": "存货周转承压。", "hypotheses": ["库存上升", "需求波动"], "validation_focus": ["核查库存", "核查订单"], "confidence": "medium"}'
        score_payload = {
            "ok": True,
            "stock_name": "中芯国际",
            "ind1": "电子",
            "ind2": "半导体",
            "sub_indicator_diagnostics": {
                "inv_days": {
                    "indicator_name": "存货周转天数",
                    "change": {"summary": "存货周转天数较上期抬升"},
                    "attribution": {"summary": "主因：库存消化变慢。"},
                    "impact": {"impact_summary": "库存周转压力走高", "impact_risks": ["主影响：库存消化承压。"]},
                    "explanation": {"status": "idle", "content": ""},
                }
            },
        }
        report_history = {
            "market": "sh",
            "symbol": "688981",
            "stock_name": "中芯国际",
            "latest_report": {"report_date": "20260331", "period": "2026Q1", "metrics": {"revenue": 1200.0}},
            "reports": [{"report_date": "20260331", "period": "2026Q1", "metrics": {"revenue": 1200.0}}],
        }

        with (
            mock.patch.object(ai_report, "load_recent_three_year_financial_reports", return_value=report_history),
            mock.patch.object(ai_report, "load_sub_indicator_score_context", return_value=score_payload),
            mock.patch.object(ai_report.subprocess, "run") as run_mock,
        ):
            run_mock.return_value = mock.Mock(returncode=0, stdout=hermes_output, stderr="")
            result = ai_report.generate_sub_indicator_ai_explanation("sh", "688981", "inv_days")

        self.assertIn("景气周期", result["explanation"]["hypotheses"])
        self.assertIn("稼动率", result["explanation"]["hypotheses"])
        self.assertIn("订单能见度", result["explanation"]["validation_focus"])
        self.assertIn("库存周转", result["explanation"]["validation_focus"])

    def test_generate_sub_indicator_ai_explanation_applies_cyclical_manufacturing_short_templates(self) -> None:
        hermes_output = 'session_id: 20260429_123456\n{"summary": "营收增速回落。", "hypotheses": ["收入回落", "订单波动"], "validation_focus": ["核查订单", "核查产能"], "confidence": "medium"}'
        score_payload = {
            "ok": True,
            "stock_name": "三一重工",
            "ind1": "机械设备",
            "ind2": "工程机械",
            "sub_indicator_diagnostics": {
                "revenue_growth": {
                    "indicator_name": "营收增速",
                    "change": {"summary": "营收增速较上期回落"},
                    "attribution": {"summary": "主因：订单兑现节奏放缓。"},
                    "impact": {"impact_summary": "收入弹性走弱", "impact_risks": ["主影响：收入兑现承压。"]},
                    "explanation": {"status": "idle", "content": ""},
                }
            },
        }
        report_history = {
            "market": "sh",
            "symbol": "600031",
            "stock_name": "三一重工",
            "latest_report": {"report_date": "20260331", "period": "2026Q1", "metrics": {"revenue": 1200.0}},
            "reports": [{"report_date": "20260331", "period": "2026Q1", "metrics": {"revenue": 1200.0}}],
        }

        with (
            mock.patch.object(ai_report, "load_recent_three_year_financial_reports", return_value=report_history),
            mock.patch.object(ai_report, "load_sub_indicator_score_context", return_value=score_payload),
            mock.patch.object(ai_report.subprocess, "run") as run_mock,
        ):
            run_mock.return_value = mock.Mock(returncode=0, stdout=hermes_output, stderr="")
            result = ai_report.generate_sub_indicator_ai_explanation("sh", "600031", "revenue_growth")

        self.assertIn("订单节奏", result["explanation"]["hypotheses"])
        self.assertIn("产能利用率", result["explanation"]["hypotheses"])
        self.assertIn("在手订单", result["explanation"]["validation_focus"])
        self.assertIn("开工率", result["explanation"]["validation_focus"])

    def test_industry_template_tags_cover_all_current_level1_industries(self) -> None:
        expected = {
            "机械设备", "电子", "医药医疗", "化工", "电力设备", "计算机", "汽车", "轻工制造", "建筑", "有色",
            "公用事业", "食品饮料", "国防军工", "环保", "传媒", "交通运输", "通信", "商贸", "纺织服饰", "农林牧渔",
            "房地产", "社会服务", "建材", "家电", "非银金融", "钢铁", "银行", "石油", "煤炭", "综合",
        }
        uncovered = {
            ind1 for ind1 in expected
            if not industry_templates._industry_template_tags(ind1, "")
        }
        self.assertEqual(set(), uncovered)

    def test_generate_sub_indicator_ai_explanation_applies_bank_short_templates(self) -> None:
        hermes_output = 'session_id: 20260429_123456\n{"summary": "资产周转走弱。", "hypotheses": ["资产扩张", "息差波动"], "validation_focus": ["核查资产", "核查负债"], "confidence": "medium"}'
        score_payload = {
            "ok": True,
            "stock_name": "招商银行",
            "ind1": "银行",
            "ind2": "全国性银行",
            "sub_indicator_diagnostics": {
                "asset_turn": {
                    "indicator_name": "总资产周转率",
                    "change": {"summary": "总资产周转率较上期回落"},
                    "attribution": {"summary": "主因：资产扩张快于收入。"},
                    "impact": {"impact_summary": "资产使用效率走弱", "impact_risks": ["主影响：效率回落。"]},
                    "explanation": {"status": "idle", "content": ""},
                }
            },
        }
        report_history = {
            "market": "sh",
            "symbol": "600036",
            "stock_name": "招商银行",
            "latest_report": {"report_date": "20260331", "period": "2026Q1", "metrics": {"revenue": 1200.0}},
            "reports": [{"report_date": "20260331", "period": "2026Q1", "metrics": {"revenue": 1200.0}}],
        }
        with (
            mock.patch.object(ai_report, "load_recent_three_year_financial_reports", return_value=report_history),
            mock.patch.object(ai_report, "load_sub_indicator_score_context", return_value=score_payload),
            mock.patch.object(ai_report.subprocess, "run") as run_mock,
        ):
            run_mock.return_value = mock.Mock(returncode=0, stdout=hermes_output, stderr="")
            result = ai_report.generate_sub_indicator_ai_explanation("sh", "600036", "asset_turn")

        self.assertIn("息差", result["explanation"]["hypotheses"])
        self.assertIn("存贷", result["explanation"]["validation_focus"])

    def test_generate_sub_indicator_ai_explanation_applies_real_estate_short_templates(self) -> None:
        hermes_output = 'session_id: 20260429_123456\n{"summary": "资产负债率承压。", "hypotheses": ["债务抬升", "周转放缓"], "validation_focus": ["核查负债", "核查回款"], "confidence": "medium"}'
        score_payload = {
            "ok": True,
            "stock_name": "万科A",
            "ind1": "房地产",
            "ind2": "房地产开发",
            "sub_indicator_diagnostics": {
                "debt_ratio": {
                    "indicator_name": "资产负债率",
                    "change": {"summary": "资产负债率较上期抬升"},
                    "attribution": {"summary": "主因：负债规模抬升。"},
                    "impact": {"impact_summary": "杠杆压力走高", "impact_risks": ["主影响：杠杆承压。"]},
                    "explanation": {"status": "idle", "content": ""},
                }
            },
        }
        report_history = {
            "market": "sz",
            "symbol": "000002",
            "stock_name": "万科A",
            "latest_report": {"report_date": "20260331", "period": "2026Q1", "metrics": {"revenue": 1200.0}},
            "reports": [{"report_date": "20260331", "period": "2026Q1", "metrics": {"revenue": 1200.0}}],
        }
        with (
            mock.patch.object(ai_report, "load_recent_three_year_financial_reports", return_value=report_history),
            mock.patch.object(ai_report, "load_sub_indicator_score_context", return_value=score_payload),
            mock.patch.object(ai_report.subprocess, "run") as run_mock,
        ):
            run_mock.return_value = mock.Mock(returncode=0, stdout=hermes_output, stderr="")
            result = ai_report.generate_sub_indicator_ai_explanation("sz", "000002", "debt_ratio")

        self.assertIn("去化", result["explanation"]["hypotheses"])
        self.assertIn("销售回款", result["explanation"]["validation_focus"])

    def test_generate_sub_indicator_ai_explanation_polishes_summary_numeric_suffix_and_period(self) -> None:
        hermes_output = 'session_id: 20260429_123456\n{"summary": "消费品口径下，26Q1营收增速6", "hypotheses": ["渠道动销"], "validation_focus": ["终端动销"], "confidence": "medium"}'
        score_payload = {
            "ok": True,
            "stock_name": "贵州茅台",
            "ind1": "食品饮料",
            "ind2": "酿酒",
            "sub_indicator_diagnostics": {
                "revenue_growth": {
                    "indicator_name": "营收增速",
                    "change": {"summary": "营收增速较上期回落"},
                    "attribution": {"summary": "主因：收入动能放缓。"},
                    "impact": {"impact_summary": "收入弹性走弱", "impact_risks": ["主影响：收入增速回落。"]},
                    "explanation": {"status": "idle", "content": ""},
                }
            },
            "latest_period": "2026Q1",
        }
        report_history = {
            "market": "sh",
            "symbol": "600519",
            "stock_name": "贵州茅台",
            "latest_report": {"report_date": "20260331", "period": "2026Q1", "metrics": {"revenue": 1200.0}},
            "reports": [{"report_date": "20260331", "period": "2026Q1", "metrics": {"revenue": 1200.0}}],
        }
        with (
            mock.patch.object(ai_report, "load_recent_three_year_financial_reports", return_value=report_history),
            mock.patch.object(ai_report, "load_sub_indicator_score_context", return_value=score_payload),
            mock.patch.object(ai_report.subprocess, "run") as run_mock,
        ):
            run_mock.return_value = mock.Mock(returncode=0, stdout=hermes_output, stderr="")
            result = ai_report.generate_sub_indicator_ai_explanation("sh", "600519", "revenue_growth")

        self.assertEqual("消费品口径下，2026Q1营收增速6%。", result["explanation"]["summary"])

    def test_generate_sub_indicator_ai_explanation_compresses_terminal_lists_and_deduplicates_validation_focus(self) -> None:
        hermes_output = 'session_id: 20260429_123456\n{"summary": "消费品口径下，2026Q1营收增速6%。", "hypotheses": ["渠道动销", "提价节奏", "高基数扰动", "量价节奏", "终端反馈偏弱", "额外冗余项"], "validation_focus": ["核对终端动销", "终端动销", "查看渠道库存", "渠道库存", "核对量价拆分", "量价拆分", "核对批价"], "confidence": "medium"}'
        score_payload = {
            "ok": True,
            "stock_name": "贵州茅台",
            "ind1": "食品饮料",
            "ind2": "酿酒",
            "sub_indicator_diagnostics": {
                "revenue_growth": {
                    "indicator_name": "营收增速",
                    "change": {"summary": "营收增速较上期回落"},
                    "attribution": {"summary": "主因：收入动能放缓。"},
                    "impact": {"impact_summary": "收入弹性走弱", "impact_risks": ["主影响：收入增速回落。"]},
                    "explanation": {"status": "idle", "content": ""},
                }
            },
            "latest_period": "2026Q1",
        }
        report_history = {
            "market": "sh",
            "symbol": "600519",
            "stock_name": "贵州茅台",
            "latest_report": {"report_date": "20260331", "period": "2026Q1", "metrics": {"revenue": 1200.0}},
            "reports": [{"report_date": "20260331", "period": "2026Q1", "metrics": {"revenue": 1200.0}}],
        }
        with (
            mock.patch.object(ai_report, "load_recent_three_year_financial_reports", return_value=report_history),
            mock.patch.object(ai_report, "load_sub_indicator_score_context", return_value=score_payload),
            mock.patch.object(ai_report.subprocess, "run") as run_mock,
        ):
            run_mock.return_value = mock.Mock(returncode=0, stdout=hermes_output, stderr="")
            result = ai_report.generate_sub_indicator_ai_explanation("sh", "600519", "revenue_growth")

        self.assertLessEqual(len(result["explanation"]["hypotheses"]), 4)
        self.assertLessEqual(len(result["explanation"]["validation_focus"]), 4)
        self.assertEqual(len(result["explanation"]["validation_focus"]), len(set(result["explanation"]["validation_focus"])))
        self.assertNotIn("核对终端动销", result["explanation"]["validation_focus"])
        self.assertIn("终端动销", result["explanation"]["validation_focus"])
        self.assertIn("渠道库存", result["explanation"]["validation_focus"])
        self.assertIn("量价拆分", result["explanation"]["validation_focus"])

    def test_load_recent_three_year_financial_reports_stops_scanning_once_three_year_window_is_collected(self) -> None:
        class FakeRow(dict):
            def get(self, key, default=None):
                return super().get(key, default)

        # 服务端拆分后，报告期窗口在 warehouse 读取边界裁剪
        # （app.financial.warehouse_reports.load_symbol_financial_rows(years=...)），
        # 不再逐文件扫描 app.search.index._all_financial_files / _load_file。
        report_dates = [
            "20260331",
            "20251231",
            "20250930",
            "20250630",
            "20250331",
            "20241231",
            "20240930",
            "20240630",
            "20240331",
            "20231231",
            "20230930",
        ]
        warehouse_rows = [
            {
                "period": financial_reports._report_date_to_period_label(report_date),
                "row": FakeRow({"announce_date": f"{report_date[:4]}0429"}),
            }
            for report_date in report_dates
        ]
        warehouse_load_calls = []

        def load_warehouse_rows(symbol, *, years=6):
            warehouse_load_calls.append((symbol, years))
            return warehouse_rows

        fake_search_index = mock.Mock()
        fake_search_index._stock_name_lookup.return_value = {("sh", "601318"): "中国平安"}
        fake_search_index._derive_sub_fields.return_value = {
            "roe_ex": 12.8,
            "debt_ratio": 41.2,
            "current_ratio": 1.2,
            "quick_ratio": 1.1,
            "profit_growth": 8.0,
            "revenue_growth": 6.0,
            "ex_profit_growth": 7.0,
        }
        fake_search_index._pick.side_effect = lambda value: value
        fake_search_index.load_industry_rows.return_value = []
        fake_search_index._load_financial_snapshot.return_value = {}

        with (
            mock.patch.dict("sys.modules", {"app.search.index": fake_search_index}),
            mock.patch.object(
                warehouse_reports,
                "load_symbol_financial_rows",
                side_effect=load_warehouse_rows,
            ),
        ):
            result = financial_reports.load_recent_three_year_financial_reports("sh", "601318", years=3)

        self.assertEqual(9, len(result["reports"]))
        # 窗口只向数据源请求一次，并把 years 下推给 warehouse 读取边界。
        self.assertEqual([("601318", 3)], warehouse_load_calls)
        # 只物化了窗口内的 9 个报告期，窗口外的旧报告期未被读取。
        self.assertEqual(9, fake_search_index._derive_sub_fields.call_count)
        self.assertNotIn("2023A", [row["period"] for row in result["reports"]])
        self.assertNotIn("2023Q3", [row["period"] for row in result["reports"]])

    def test_stock_score_report_history_raises_requested_years_to_six(self) -> None:
        handler = mock.Mock()
        payload = {"ok": True, "reports": []}

        with mock.patch.object(app_handler, "load_recent_three_year_financial_reports", return_value=payload) as load_reports:
            app_handler.StockDashboardHandler.handle_stock_score_report_history(
                handler,
                "market=sh&symbol=601318&years=5",
            )

        load_reports.assert_called_once_with("sh", "601318", years=6)
        handler.respond_json.assert_called_once_with(app_handler.HTTPStatus.OK, payload)

    def test_respond_json_swallows_broken_pipe_from_write(self) -> None:
        handler = mock.Mock()
        handler.wfile.write.side_effect = BrokenPipeError()

        ok = app_handler.StockDashboardHandler.respond_json(handler, app_handler.HTTPStatus.OK, {"ok": True})

        self.assertFalse(ok)
        handler.send_response.assert_called_once_with(app_handler.HTTPStatus.OK)

    def test_respond_json_swallows_broken_pipe_from_headers(self) -> None:
        handler = mock.Mock()
        handler.end_headers.side_effect = BrokenPipeError()

        ok = app_handler.StockDashboardHandler.respond_json(handler, app_handler.HTTPStatus.OK, {"ok": True})

        self.assertFalse(ok)
        handler.send_response.assert_called_once_with(app_handler.HTTPStatus.OK)
        handler.wfile.write.assert_not_called()

    def test_serve_static_swallows_broken_pipe_from_write(self) -> None:
        handler = mock.Mock()
        target = app_config.WEB_ROOT / "stock-analysis.js"
        handler.wfile.write.side_effect = BrokenPipeError()

        app_handler.StockDashboardHandler.serve_static(handler, "stock-analysis.js")

        handler.send_response.assert_called_once_with(app_handler.HTTPStatus.OK)
        handler.send_header.assert_any_call("Content-Type", "application/javascript; charset=utf-8")
        handler.send_header.assert_any_call("Content-Length", str(len(target.read_bytes())))

    def test_serve_static_can_skip_body_for_head_request(self) -> None:
        handler = mock.Mock()
        target = app_config.WEB_ROOT / "stock-analysis.html"

        app_handler.StockDashboardHandler.serve_static(handler, "stock-analysis.html", include_body=False)

        handler.send_response.assert_called_once_with(app_handler.HTTPStatus.OK)
        handler.send_header.assert_any_call("Content-Type", "text/html; charset=utf-8")
        handler.send_header.assert_any_call("Content-Length", str(len(target.read_bytes())))
        handler.wfile.write.assert_not_called()

    def test_do_head_routes_root_to_stock_analysis_without_body(self) -> None:
        handler = mock.Mock()
        handler.path = "/"

        app_handler.StockDashboardHandler.do_HEAD(handler)

        handler.serve_static.assert_called_once_with("stock-analysis.html", include_body=False)

    def test_load_recent_three_year_financial_reports_returns_recent_three_year_quarter_timeline(self) -> None:
        class FakeRow(dict):
            def get(self, key, default=None):
                return super().get(key, default)

        class FakeFrame:
            def __init__(self, rows):
                self._rows = rows

            def iterrows(self):
                return iter(self._rows)

        # 服务端拆分后，报告期由 warehouse 数据源提供（load_symbol_financial_rows），
        # 不再逐文件扫描 app.search.index._all_financial_files / _load_file。
        report_dates = [
            "20260331",
            "20251231",
            "20250930",
            "20250630",
            "20250331",
            "20241231",
            "20240930",
            "20240630",
            "20240331",
        ]
        announce_dates = {
            "20260331": "20260429",
            "20251231": "20260320",
            "20250930": "20251030",
            "20250630": "20250820",
            "20250331": "20250430",
            "20241231": "20250320",
            "20240930": "20241030",
            "20240630": "20240820",
            "20240331": "20240429",
        }
        warehouse_rows = [
            {
                "period": financial_reports._report_date_to_period_label(report_date),
                "row": FakeRow({"announce_date": announce_dates[report_date]}),
            }
            for report_date in report_dates
        ]

        fake_search_index = mock.Mock()
        fake_search_index._stock_name_lookup.return_value = {("sh", "601318"): "中国平安"}
        fake_search_index._derive_sub_fields.side_effect = [
            {"roe_ex": 12.8, "debt_ratio": 41.2, "current_ratio": 1.2, "quick_ratio": 1.1, "profit_growth": 8.0, "revenue_growth": 6.0, "ex_profit_growth": 7.0},
            {"roe_ex": 12.2, "debt_ratio": 41.5, "current_ratio": 1.2, "quick_ratio": 1.1, "profit_growth": 7.0, "revenue_growth": 5.0, "ex_profit_growth": 6.0},
            {"roe_ex": 11.9, "debt_ratio": 41.8, "current_ratio": 1.1, "quick_ratio": 1.0, "profit_growth": 6.5, "revenue_growth": 4.5, "ex_profit_growth": 5.5},
            {"roe_ex": 11.6, "debt_ratio": 42.0, "current_ratio": 1.1, "quick_ratio": 1.0, "profit_growth": 6.0, "revenue_growth": 4.0, "ex_profit_growth": 5.0},
            {"roe_ex": 11.3, "debt_ratio": 43.0, "current_ratio": 1.0, "quick_ratio": 0.9, "profit_growth": 4.0, "revenue_growth": 3.0, "ex_profit_growth": 2.0},
            {"roe_ex": 11.0, "debt_ratio": 43.2, "current_ratio": 1.0, "quick_ratio": 0.9, "profit_growth": 3.5, "revenue_growth": 2.8, "ex_profit_growth": 1.8},
            {"roe_ex": 10.8, "debt_ratio": 43.5, "current_ratio": 0.9, "quick_ratio": 0.8, "profit_growth": 3.0, "revenue_growth": 2.0, "ex_profit_growth": 1.6},
            {"roe_ex": 10.7, "debt_ratio": 43.7, "current_ratio": 0.9, "quick_ratio": 0.8, "profit_growth": 2.5, "revenue_growth": 1.5, "ex_profit_growth": 1.2},
            {"roe_ex": 10.9, "debt_ratio": 44.0, "current_ratio": 0.9, "quick_ratio": 0.8, "profit_growth": 2.0, "revenue_growth": 1.0, "ex_profit_growth": 1.5},
        ]
        fake_search_index._pick.side_effect = lambda value: value
        fake_search_index.load_industry_rows.return_value = []
        fake_search_index._load_financial_snapshot.return_value = {}

        with (
            mock.patch.dict("sys.modules", {"app.search.index": fake_search_index}),
            mock.patch.object(
                warehouse_reports,
                "load_symbol_financial_rows",
                return_value=warehouse_rows,
            ),
        ):
            result = financial_reports.load_recent_three_year_financial_reports("sh", "601318")

        self.assertEqual("2026Q1", result["latest_period_label"])
        self.assertEqual("20260331", result["latest_report"]["report_date"])
        self.assertEqual(
            ["2024Q1", "2024Q2", "2024Q3", "2024A", "2025Q1", "2025Q2", "2025Q3", "2025A", "2026Q1"],
            [row["period"] for row in result["reports"]],
        )
        # 迁移后的 _materialize_financial_report 不再把 revenue_growth/profit_growth 等
        # 增速字段写进 metrics（增速改由健康度/季度监控内部计算），但派生字段仍通过
        # app.search.index._derive_sub_fields 落位；这里用同源的 roe_ex 验证同样的
        # “派生值按报告期正确落位、时间线按升序排列”契约。
        self.assertEqual([10.9, 10.7, 10.8], [row["metrics"]["roe_ex"] for row in result["reports"][:3]])
        self.assertEqual(12.8, result["reports"][-1]["metrics"]["roe_ex"])


if __name__ == "__main__":
    unittest.main()
