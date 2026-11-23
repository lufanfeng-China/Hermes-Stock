import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app import handler as app_handler
from app.financial.sector_external_update import FinancialSectorStatusStore


ROOT = Path(__file__).resolve().parents[1]


class FinancialSectorUpdateApiTests(unittest.TestCase):
    def test_data_update_page_separates_current_and_previous_quarterly_scores(self) -> None:
        html = (ROOT / "web" / "data-update.html").read_text(encoding="utf-8")
        self.assertIn("当前季报分", html)
        self.assertIn("上一可信季报", html)
        self.assertIn("previous_quarterly_score", html)

    def test_status_api_returns_per_symbol_rows_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = FinancialSectorStatusStore(root)
            store.save_symbol_status({
                "symbol": "600036", "name": "招商银行", "sector_model": "bank",
                "status": "up_to_date", "latest_announced_period": "2026Q3",
                "latest_valid_period": "2026Q3", "latest_scored_period": "2026Q3",
                "quarterly_score": 81.0,
            })
            store.save_symbol_status({
                "symbol": "600030", "name": "中信证券", "sector_model": "securities",
                "status": "parse_failed", "latest_announced_period": "2026Q3",
                "latest_valid_period": "2026H1", "latest_scored_period": "2026H1",
                "previous_quarterly_score": 73.0,
            })
            request = Mock()
            with (
                patch.object(app_handler, "FINANCIAL_SECTOR_STATUS_DIR", root),
                patch.object(app_handler, "financial_sector_expected_symbols", return_value=["600036", "600030"]),
            ):
                app_handler.StockDashboardHandler.handle_financial_sector_update_status(request, "")

        status, payload = request.respond_json.call_args.args
        self.assertEqual(app_handler.HTTPStatus.OK, status)
        self.assertTrue(payload["ok"])
        self.assertEqual(2, payload["summary"]["total"])
        self.assertEqual(1, payload["summary"]["status_counts"]["up_to_date"])
        self.assertEqual(1, payload["summary"]["status_counts"]["parse_failed"])
        self.assertEqual(["600030", "600036"], [row["symbol"] for row in payload["stocks"]])

    def test_retry_api_posts_one_symbol_only(self) -> None:
        body = json.dumps({"symbol": "600036", "report_period": "2026Q3", "source_type": "quarterly_report"}).encode()
        request = Mock()
        request.headers = {"Origin": "http://127.0.0.1:8765", "Content-Length": str(len(body))}
        request.rfile = io.BytesIO(body)
        with (
            patch.object(app_handler, "_is_allowed_local_origin", return_value=True),
            patch.object(app_handler, "start_financial_sector_symbol_retry", return_value={
                "ok": True, "started": True, "symbol": "600036", "status": "queued"
            }) as start,
        ):
            app_handler.StockDashboardHandler.handle_financial_sector_update_retry(request)

        start.assert_called_once_with("600036", report_period="2026Q3", source_type="quarterly_report")
        status, payload = request.respond_json.call_args.args
        self.assertEqual(app_handler.HTTPStatus.OK, status)
        self.assertTrue(payload["started"])
        self.assertEqual("600036", payload["symbol"])

    def test_handler_registers_get_status_and_post_retry_routes(self) -> None:
        source = Path(app_handler.__file__).read_text(encoding="utf-8")
        self.assertIn('parsed.path == "/api/financial-sector-update-status"', source)
        self.assertIn('parsed.path == "/api/financial-sector-update-retry"', source)


if __name__ == "__main__":
    unittest.main()
