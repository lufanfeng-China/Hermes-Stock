import importlib
import importlib.util
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


class FinancialSectorExternalUpdateTests(unittest.TestCase):
    def test_cninfo_post_disables_redirects_and_rejects_changed_final_origin(self) -> None:
        script = importlib.import_module("scripts.update_financial_sector_external")
        response = Mock()
        response.url = "https://evil.example/new/hisAnnouncement/query"
        response.is_redirect = False
        response.is_permanent_redirect = False
        response.raise_for_status.return_value = None
        response.json.return_value = {"announcements": []}
        session = Mock()
        session.post.return_value = response

        with patch.object(script.time, "sleep"), self.assertRaises(script.ExternalUpdateError):
            script._request_json(session, data={"pageNum": "1"})

        self.assertEqual(3, session.post.call_count)
        self.assertTrue(all(call.kwargs["allow_redirects"] is False for call in session.post.call_args_list))

    def test_per_symbol_status_store_persists_and_summarizes_without_losing_previous_score(self) -> None:
        spec = importlib.util.find_spec("app.financial.sector_external_update")
        self.assertIsNotNone(spec, "金融行业逐股外部数据状态模块尚未实现")
        module = importlib.import_module("app.financial.sector_external_update")

        with tempfile.TemporaryDirectory() as directory:
            store = module.FinancialSectorStatusStore(Path(directory))
            store.save_symbol_status({
                "symbol": "600036",
                "name": "招商银行",
                "sector_model": "bank",
                "latest_announced_period": "2026Q3",
                "latest_valid_period": "2026H1",
                "latest_scored_period": "2026H1",
                "status": "parse_failed",
                "previous_quarterly_score": 74.0,
                "previous_quarterly_period": "2026H1",
                "last_error": {"code": "table_not_found", "message": "未找到监管指标表"},
            })
            store.save_symbol_status({
                "symbol": "600030",
                "name": "中信证券",
                "sector_model": "securities",
                "latest_announced_period": "2026Q3",
                "latest_valid_period": "2026Q3",
                "latest_scored_period": "2026Q3",
                "status": "up_to_date",
                "quarterly_score": 81.0,
            })

            bank = store.load_symbol_status("600036")
            self.assertEqual("parse_failed", bank["status"])
            self.assertEqual(74.0, bank["previous_quarterly_score"])
            self.assertEqual("2026H1", bank["previous_quarterly_period"])
            self.assertEqual("table_not_found", bank["last_error"]["code"])

            summary = store.build_summary(expected_symbols=["600036", "600030"])
            self.assertEqual(2, summary["total"])
            self.assertEqual(1, summary["status_counts"]["up_to_date"])
            self.assertEqual(1, summary["status_counts"]["parse_failed"])
            self.assertEqual(0, summary["missing_status_count"])
            self.assertEqual(2, sum(summary["status_counts"].values()))

            persisted = json.loads((Path(directory) / "current_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary, persisted)

    def test_batch_isolates_one_failure_and_retry_only_reprocesses_that_symbol(self) -> None:
        module = importlib.import_module("app.financial.sector_external_update")

        with tempfile.TemporaryDirectory() as directory:
            store = module.FinancialSectorStatusStore(Path(directory))
            for symbol, name, sector in (
                ("600036", "招商银行", "bank"),
                ("600030", "中信证券", "securities"),
            ):
                store.save_symbol_status({
                    "symbol": symbol,
                    "name": name,
                    "sector_model": sector,
                    "latest_announced_period": "2026Q3",
                    "latest_valid_period": "2026H1",
                    "latest_scored_period": "2026H1",
                    "status": "queued",
                    "previous_quarterly_score": 70.0,
                    "previous_quarterly_period": "2026H1",
                })

            processed: list[str] = []

            def first_attempt(request: dict[str, object]) -> dict[str, object]:
                symbol = str(request["symbol"])
                processed.append(symbol)
                if symbol == "600036":
                    raise module.ExternalUpdateError("pdf_download_failed", "PDF下载失败")
                return {
                    "latest_valid_period": "2026Q3",
                    "latest_scored_period": "2026Q3",
                    "quarterly_score": 81.0,
                    "status": "up_to_date",
                }

            result = module.run_symbol_updates([
                {"symbol": "600036"},
                {"symbol": "600030"},
            ], processor=first_attempt, store=store)

            self.assertEqual(["600036", "600030"], processed)
            self.assertEqual(1, result["succeeded"])
            self.assertEqual(1, result["failed"])
            failed = store.load_symbol_status("600036")
            self.assertEqual("download_failed", failed["status"])
            self.assertEqual("pdf_download_failed", failed["last_error"]["code"])
            self.assertEqual(70.0, failed["previous_quarterly_score"])
            self.assertEqual("2026H1", failed["latest_scored_period"])
            self.assertEqual("up_to_date", store.load_symbol_status("600030")["status"])

            retried: list[str] = []

            def retry_processor(request: dict[str, object]) -> dict[str, object]:
                retried.append(str(request["symbol"]))
                return {
                    "latest_valid_period": "2026Q3",
                    "latest_scored_period": "2026Q3",
                    "quarterly_score": 78.0,
                    "status": "up_to_date",
                    "last_error": None,
                }

            retry_result = module.retry_symbol_update("600036", processor=retry_processor, store=store)
            self.assertEqual(["600036"], retried)
            self.assertTrue(retry_result["ok"])
            self.assertEqual(78.0, store.load_symbol_status("600036")["quarterly_score"])
            self.assertEqual(81.0, store.load_symbol_status("600030")["quarterly_score"])
    def test_cninfo_title_classification_and_metric_table_extraction(self) -> None:
        module = importlib.import_module("app.financial.sector_external_update")

        self.assertEqual(
            {"report_period": "2026Q3", "source_type": "pillar3_report"},
            module.classify_cninfo_report_title("招商银行股份有限公司2026年第三季度第三支柱报告"),
        )
        self.assertEqual(
            {"report_period": "2026Q3", "source_type": "quarterly_report"},
            module.classify_cninfo_report_title("中信证券股份有限公司2026年第三季度报告"),
        )
        self.assertEqual(
            {"report_period": "2026Q3", "source_type": "quarterly_report"},
            module.classify_cninfo_report_title("申万宏源集团股份有限公司2026年三季度报告"),
        )
        self.assertEqual(
            {"report_period": "2026Q1", "source_type": "quarterly_report"},
            module.classify_cninfo_report_title("申万宏源集团股份有限公司2026年一季度报告"),
        )
        self.assertEqual(
            {"report_period": "2025A", "source_type": "annual_report"},
            module.classify_cninfo_report_title("中信证券股份有限公司2025年年度报告"),
        )
        self.assertIsNone(module.classify_cninfo_report_title("中信证券股份有限公司2025年年度报告摘要"))
        self.assertIsNone(module.classify_cninfo_report_title("境内同步披露公告-2026年第三季度报告（H股）"))
        self.assertIsNone(module.classify_cninfo_report_title("苏农银行年度报告信息披露重大差错责任追究制度（2026年修订）"))

        bank_lines = [
            "资产质量指标(%)", "2025年", "12月31日", "拨备覆盖率(1)", "391.79", "411.98", "下降20.19个百分点",
            "核心一级资本充足率", "14.16", "14.86", "下降0.70个百分点",
        ]
        evidence = module.extract_labeled_number(
            bank_lines, aliases=("拨备覆盖率",), minimum=0, maximum=1000,
        )
        self.assertEqual(391.79, evidence["value"])
        self.assertEqual("拨备覆盖率(1)", evidence["raw_label"])

        securities_lines = [
            "风险覆盖率（%）", "213.06", "187.21", "资本杠杆率（%）", "15.06", "16.32",
        ]
        risk = module.extract_labeled_number(
            securities_lines, aliases=("风险覆盖率",), minimum=0, maximum=1000,
        )
        self.assertEqual(213.06, risk["value"])
        liquidity = module.extract_labeled_number(
            ["流动性覆盖率", "≥100", "220.30", "227.29"],
            aliases=("流动性覆盖率",), minimum=0, maximum=5000,
        )
        self.assertEqual(220.30, liquidity["value"])
        nsfr = module.extract_labeled_number(
            ["5. 净稳定资金比例", "本集团2025年第四季度净稳定资金比例季末时点值为142.02%"],
            aliases=("净稳定资金比例",), minimum=0, maximum=5000,
        )
        self.assertEqual(142.02, nsfr["value"])

        script = importlib.import_module("scripts.update_financial_sector_external")
        business_metrics = script._extract_metrics(
            [(1, ["资产管理业务净收入", "123456789", "投资银行业务净收入", "98765432"])],
            "securities",
        )
        self.assertEqual(123456789.0, business_metrics["asset_management_net_revenue"]["value"])
        self.assertEqual(98765432.0, business_metrics["investment_banking_net_revenue"]["value"])

    def test_select_cninfo_reports_keeps_latest_revision_per_period_and_source(self) -> None:
        module = importlib.import_module("app.financial.sector_external_update")
        announcements = [
            {"secCode": "600036", "announcementTitle": "招商银行股份有限公司2025年度报告", "announcementTime": 10, "announcementId": "old", "adjunctUrl": "old.PDF"},
            {"secCode": "600036", "announcementTitle": "招商银行股份有限公司2025年度报告（修订版）", "announcementTime": 20, "announcementId": "new", "adjunctUrl": "new.PDF"},
            {"secCode": "600036", "announcementTitle": "招商银行股份有限公司2025年度报告摘要", "announcementTime": 30, "announcementId": "summary", "adjunctUrl": "summary.PDF"},
            {"secCode": "600036", "announcementTitle": "招商银行股份有限公司2026年第三季度报告", "announcementTime": 40, "announcementId": "q3", "adjunctUrl": "q3.PDF"},
            {"secCode": "600030", "announcementTitle": "中信证券股份有限公司2025年度报告", "announcementTime": 50, "announcementId": "other", "adjunctUrl": "other.PDF"},
        ]
        selected = module.select_cninfo_reports(announcements, symbol="600036")
        self.assertEqual(["2025A:annual_report", "2026Q3:quarterly_report"], [row["report_key"] for row in selected])
        self.assertEqual("new", selected[0]["announcement_id"])
        self.assertEqual("https://static.cninfo.com.cn/new.PDF", selected[0]["source_url"])

        malicious = [{
            "secCode": "600036", "announcementTitle": "招商银行股份有限公司2025年度报告",
            "announcementTime": 99, "announcementId": "evil", "adjunctUrl": "http://127.0.0.1/private.pdf",
        }]
        self.assertEqual([], module.select_cninfo_reports(malicious, symbol="600036"))
        self.assertIsNone(module.normalize_cninfo_pdf_url("https://evil.example/report.pdf"))
        self.assertEqual(
            "https://static.cninfo.com.cn/finalpage/report.pdf",
            module.normalize_cninfo_pdf_url("finalpage/report.pdf"),
        )

    def test_full_discovery_prunes_invalid_old_report_keys_but_targeted_retry_keeps_them(self) -> None:
        script = importlib.import_module("scripts.update_financial_sector_external")
        previous = {
            "2025A:annual_report": {"status": "published"},
            "2026A:annual_report": {"status": "published"},
            "2026Q3:quarterly_report": {"status": "published"},
        }
        discovered = [
            {"report_key": "2025A:annual_report"},
            {"report_key": "2026Q3:quarterly_report"},
        ]
        self.assertEqual(
            {"2025A:annual_report", "2026Q3:quarterly_report"},
            set(script._initial_report_states(previous, discovered, targeted=False)),
        )
        self.assertEqual(set(previous), set(script._initial_report_states(previous, discovered, targeted=True)))
        self.assertEqual("2026Q3", script._latest_announced_period("2026A", "2026Q3", targeted=False))
        self.assertEqual("2026A", script._latest_announced_period("2026A", "2026Q3", targeted=True))

    def test_current_announcement_query_collects_every_cninfo_page(self) -> None:
        script = importlib.import_module("scripts.update_financial_sector_external")
        pages = [
            {"announcements": [{"announcementId": "p1"}], "totalpages": 2, "hasMore": True},
            {"announcements": [{"announcementId": "p2"}], "totalpages": 2, "hasMore": False},
        ]
        with patch.object(script, "_request_json", side_effect=pages) as request:
            rows = script._request_all_announcements(object(), data={"pageNum": "1", "pageSize": "30"})
        self.assertEqual(["p1", "p2"], [row["announcementId"] for row in rows])
        self.assertEqual(["1", "2"], [call.kwargs["data"]["pageNum"] for call in request.call_args_list])

    def test_latest_report_is_redownloaded_for_hash_verification(self) -> None:
        script = importlib.import_module("scripts.update_financial_sector_external")
        existing = {"status": "published", "announcement_id": "same", "announcement_time": 10,
                    "source_url": "https://static.cninfo.com.cn/a.pdf"}
        report = {"announcement_id": "same", "announcement_time": 10,
                  "source_url": "https://static.cninfo.com.cn/a.pdf"}
        self.assertFalse(script._can_reuse_published_report(existing, report, verify_hash=False))
        self.assertFalse(script._can_reuse_published_report(existing, report, verify_hash=True))
        self.assertFalse(script._can_reuse_published_report(existing, {**report, "announcement_time": 11}, verify_hash=False))

    def test_old_published_annual_is_redownloaded_when_same_url_content_changes(self) -> None:
        script = importlib.import_module("scripts.update_financial_sector_external")
        annual = {
            "report_key": "2025A:annual_report", "report_period": "2025A",
            "source_type": "annual_report", "announcement_id": "same",
            "announcement_time": 10, "source_url": "https://static.cninfo.com.cn/a.pdf",
        }
        latest = {
            "report_key": "2026Q3:quarterly_report", "report_period": "2026Q3",
            "source_type": "quarterly_report", "announcement_id": "latest",
            "announcement_time": 20, "source_url": "https://static.cninfo.com.cn/q.pdf",
        }
        request = {
            "symbol": "600036", "name": "招商银行", "market": "sh", "sector_model": "bank",
            "reports": {annual["report_key"]: {
                "status": "published", "announcement_id": "same", "announcement_time": 10,
                "source_url": annual["source_url"], "pdf_sha256": "old-digest",
                "report_period": "2025A", "source_type": "annual_report", "fields": ["npl_ratio"],
            }},
        }
        changed = b"%PDF changed old annual"
        metrics = {"npl_ratio": {"value": 1.0, "quality": 100}}
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(script, "RAW_DIR", Path(directory) / "raw"), \
             patch.object(script, "EVIDENCE_DIR", Path(directory) / "evidence"), \
             patch.object(script, "discover_reports", return_value=[annual, latest]), \
             patch.object(script, "_download_pdf", return_value=changed) as download, \
             patch.object(script, "_pdf_pages", return_value=[]), \
             patch.object(script, "_extract_metrics", return_value=metrics):
            result = script._process_stock(
                request, session=Mock(), report_period="2025A", source_type="annual_report",
            )
        download.assert_called_once_with(unittest.mock.ANY, annual["source_url"])
        self.assertEqual(
            hashlib.sha256(changed).hexdigest(),
            result["reports"][annual["report_key"]]["pdf_sha256"],
        )

    def test_unchanged_downloaded_hash_reuses_published_evidence_without_reparse(self) -> None:
        script = importlib.import_module("scripts.update_financial_sector_external")
        content = b"%PDF unchanged"
        digest = hashlib.sha256(content).hexdigest()
        report = {
            "report_key": "2025A:annual_report", "report_period": "2025A",
            "source_type": "annual_report", "announcement_id": "same",
            "announcement_time": 10, "source_url": "https://static.cninfo.com.cn/a.pdf",
        }
        published = {
            "status": "published", "announcement_id": "same", "announcement_time": 10,
            "source_url": report["source_url"], "pdf_sha256": digest,
            "report_period": "2025A", "source_type": "annual_report",
            "fields": ["npl_ratio"], "field_quality": {"npl_ratio": 100},
        }
        request = {
            "symbol": "600036", "name": "招商银行", "market": "sh", "sector_model": "bank",
            "reports": {report["report_key"]: published},
        }
        with patch.object(script, "discover_reports", return_value=[report]), \
             patch.object(script, "_download_pdf", return_value=content), \
             patch.object(script, "_pdf_pages", side_effect=AssertionError("same hash must not reparse")):
            result = script._process_stock(request, session=Mock())
        state = result["reports"][report["report_key"]]
        self.assertEqual(["npl_ratio"], state["fields"])
        self.assertEqual(digest, state["pdf_sha256"])
        self.assertIn("last_verified_at", state)

    def test_reparse_cannot_replace_published_evidence_with_fewer_fields(self) -> None:
        script = importlib.import_module("scripts.update_financial_sector_external")
        existing = {"status": "published", "fields": ["a", "b", "c"]}
        self.assertTrue(script._would_regress_published_fields(existing, {"a": {}}))
        valid = {field: {"value": 1.0, "quality": 80} for field in ("a", "b", "c", "d")}
        self.assertFalse(script._would_regress_published_fields(existing, valid))

    def test_reparse_rejects_same_fields_when_quality_drops_or_value_is_not_finite(self) -> None:
        script = importlib.import_module("scripts.update_financial_sector_external")
        existing = {
            "status": "published", "fields": ["a"], "field_quality": {"a": 95},
        }
        self.assertTrue(script._would_regress_published_fields(
            existing, {"a": {"quality": 90, "value": 1.0}},
        ))
        self.assertTrue(script._would_regress_published_fields(
            existing, {"a": {"quality": 95, "value": float("nan")}},
        ))
        self.assertFalse(script._would_regress_published_fields(
            existing, {"a": {"quality": 96, "value": 1.0}},
        ))


if __name__ == "__main__":
    unittest.main()
