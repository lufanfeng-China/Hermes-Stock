import unittest
from unittest.mock import patch


class FirstWaveSnapshotTest(unittest.TestCase):
    def test_response_groups_results_and_applies_deterministic_sort(self):
        from app.first_wave_snapshot import response_from_rows
        rows = [
            {"classification": "FIRST_WAVE_ELIGIBLE", "total_score": 80, "stage": "EARLY_CONFIRMATION", "distance_to_pressure_pct": 2, "market": "sz", "symbol": "000002"},
            {"classification": "FIRST_WAVE_ELIGIBLE", "total_score": 80, "stage": "FIRST_BREAKOUT", "distance_to_pressure_pct": 3, "market": "sz", "symbol": "000001"},
            {"classification": "FIRST_WAVE_WATCH", "total_score": 71, "stage": "FIRST_BREAKOUT", "distance_to_pressure_pct": 1, "market": "sh", "symbol": "600001"},
            {"classification": "REBASE_REVIEW", "total_score": 69, "stage": "FIRST_BREAKOUT", "distance_to_pressure_pct": 1, "market": "sh", "symbol": "600002"},
        ]
        result = response_from_rows(rows, as_of_date="2026-10-16", data_date="2026-10-16", historical=False)
        self.assertEqual(["000001", "000002"], [x["symbol"] for x in result["groups"]["main"]])
        self.assertEqual(1, result["counts"]["first_wave_watch"])
        self.assertEqual(1, result["counts"]["rebase_review"])


if __name__ == "__main__":
    unittest.main()
