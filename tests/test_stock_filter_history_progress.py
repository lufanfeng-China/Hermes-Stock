import tempfile
import unittest
from pathlib import Path


class StockFilterHistoryProgressTest(unittest.TestCase):
    def test_write_and_read_progress_exposes_bounded_percent_and_stage(self):
        from app.stock_filter_history_progress import read_progress, write_progress

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_progress(root, "2025-04-18", stage="计算历史爆量突破量价与趋势", percent=58.4, completed=3000, total=5300)
            progress = read_progress(root, "2025-04-18")

        self.assertEqual("计算历史爆量突破量价与趋势", progress["stage"])
        self.assertEqual(58, progress["percent"])
        self.assertEqual(3000, progress["completed"])
        self.assertEqual(5300, progress["total"])


if __name__ == "__main__":
    unittest.main()
