import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = PROJECT_ROOT / "web"


class RelativeValuationPageRemovalTests(unittest.TestCase):
    def test_standalone_relative_valuation_page_assets_are_removed(self) -> None:
        self.assertFalse((WEB_ROOT / "relative-valuation.html").exists())
        self.assertFalse((WEB_ROOT / "relative-valuation.js").exists())

    def test_navigation_no_longer_links_to_relative_valuation_page(self) -> None:
        for filename in ("index.html", "stock-score.html", "stock-screener.html"):
            html = (WEB_ROOT / filename).read_text(encoding="utf-8")
            self.assertNotIn('/relative-valuation.html', html)
            self.assertNotIn('>相对估值</a>', html)


if __name__ == "__main__":
    unittest.main()
