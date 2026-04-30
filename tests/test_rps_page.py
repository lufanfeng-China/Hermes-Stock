import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = PROJECT_ROOT / "web"


class RpsPageTemplateTests(unittest.TestCase):
    def test_homepage_links_to_rps_pool_page(self) -> None:
        html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="/rps-pool.html"', html)
        # Old rps-ranking page is gone
        self.assertNotIn('href="/rps-ranking.html"', html)

    def test_rps_pool_page_exists_and_has_pool_section(self) -> None:
        html = (WEB_ROOT / "rps-pool.html").read_text(encoding="utf-8")
        # Pool filter form
        self.assertIn('id="pool-level1"', html)
        self.assertIn('id="pool-level2"', html)
        self.assertIn('id="pool-concept-input"', html)
        # Pool results table
        self.assertIn('id="pool-tbody"', html)
        # Full ranking section
        self.assertIn('id="rps-ranking-form"', html)
        self.assertIn('id="rps-ranking-tbody"', html)
        # K-line chart section
        self.assertIn('id="pool-chart-section"', html)

    def test_rps_pool_page_has_no_rps_profile(self) -> None:
        html = (WEB_ROOT / "rps-pool.html").read_text(encoding="utf-8")
        # RPS Profile (old card) should not exist
        self.assertNotIn('id="rps-profile-title"', html)
        self.assertNotIn('id="rps-profile-card"', html)


if __name__ == "__main__":
    unittest.main()
