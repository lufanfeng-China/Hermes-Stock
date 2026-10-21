import importlib.util
from pathlib import Path
import unittest
import pandas as pd

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "analyze_first_wave_score_buckets.py"


def module():
    spec = importlib.util.spec_from_file_location("analyze_first_wave_score_buckets", SCRIPT)
    result = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(result)
    return result


class FirstWaveScoreBucketTests(unittest.TestCase):
    def test_summary_keeps_empty_buckets_and_uses_complete_horizons_only(self):
        mod = module()
        frame = pd.DataFrame({
            "total_score": [59.5, 70.0, 80.0],
            "return_5d_pct": [1.0, None, -1.0],
            "return_10d_pct": [2.0, None, -2.0],
            "return_20d_pct": [3.0, None, -3.0],
            "max_drawdown_5d_pct": [-1.0, None, -2.0],
            "max_drawdown_10d_pct": [-2.0, None, -3.0],
            "max_drawdown_20d_pct": [-3.0, None, -4.0],
        })
        result = mod.summarize(frame)
        self.assertEqual(1, result["<60"]["20d"]["complete_samples"])
        self.assertIsNone(result["70–79.5"]["20d"]["mean_return_pct"])
        self.assertEqual(-3.0, result["≥80"]["20d"]["mean_return_pct"])
        self.assertIn("20", result["score_return_spearman"])


if __name__ == "__main__":
    unittest.main()
