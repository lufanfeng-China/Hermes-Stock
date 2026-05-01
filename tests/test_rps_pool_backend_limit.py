import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class RpsPoolBackendLimitTests(unittest.TestCase):
    def test_pool_filter_endpoint_allows_full_pool_limit(self) -> None:
        script = (PROJECT_ROOT / "scripts" / "serve_stock_dashboard.py").read_text(encoding="utf-8")
        block = script.split('def handle_pool_filter(self, query: str) -> None:', 1)[1].split('def handle_industry_hierarchy', 1)[0]
        self.assertIn('params.get("limit", ["99999"])', block)
        self.assertIn('default=99999, maximum=99999', block)


if __name__ == "__main__":
    unittest.main()
