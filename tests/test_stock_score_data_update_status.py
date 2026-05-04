import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class StockScoreDataUpdateStatusContractTests(unittest.TestCase):
    def test_dashboard_script_registers_data_update_status_route_and_handler(self) -> None:
        script = (PROJECT_ROOT / 'scripts' / 'serve_stock_dashboard.py').read_text(encoding='utf-8')
        self.assertIn('if parsed.path == "/api/data-update-status":', script)
        self.assertIn('self.handle_data_update_status(parsed.query)', script)
        self.assertIn('def handle_data_update_status(self, query: str) -> None:', script)

    def test_dashboard_script_registers_data_update_run_post_route_and_handler(self) -> None:
        script = (PROJECT_ROOT / 'scripts' / 'serve_stock_dashboard.py').read_text(encoding='utf-8')
        self.assertIn('def do_POST(self) -> None:', script)
        self.assertIn('if parsed.path == "/api/data-update-run":', script)
        self.assertIn('self.handle_data_update_run()', script)
        self.assertIn('def handle_data_update_run(self) -> None:', script)
        self.assertIn('run_full_data_update', script)
        self.assertIn('_is_allowed_local_origin', script)
        self.assertIn("self.headers.get('Referer')", script)
        self.assertIn('forbidden_origin', script)
        self.assertIn('scripts/update_financial_ts.py', script)
        self.assertIn('scripts/build_financial_snapshot_from_warehouse.py', script)
        self.assertIn('scripts/build_industry_relative_valuation_snapshot.py', script)

    def test_dashboard_script_uses_stock_score_page_as_root_homepage(self) -> None:
        script = (PROJECT_ROOT / 'scripts' / 'serve_stock_dashboard.py').read_text(encoding='utf-8')
        self.assertIn('if parsed.path == "/":', script)
        self.assertIn('self.serve_static("stock-score.html")', script)

    def test_dashboard_script_exposes_financial_snapshot_and_industry_valuation_dates(self) -> None:
        script = (PROJECT_ROOT / 'scripts' / 'serve_stock_dashboard.py').read_text(encoding='utf-8')
        self.assertIn('financial_snapshot', script)
        self.assertIn('industry_valuation', script)
        self.assertIn('updated_at', script)
        self.assertIn('report_date', script)
        self.assertIn('latest_updated_at', script)
