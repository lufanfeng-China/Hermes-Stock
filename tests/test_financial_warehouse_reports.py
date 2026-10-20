import tempfile
import unittest
from pathlib import Path

import pandas as pd


class FinancialWarehouseReportsTests(unittest.TestCase):
    def test_load_symbol_rows_returns_only_requested_symbol_and_recent_window(self):
        from app.financial.warehouse_reports import load_symbol_financial_rows

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for period, values in {
                "2024A": [("600001", 10), ("600002", 20)],
                "2025A": [("600001", 30), ("600002", 40)],
                "2026Q1": [("600001", 50), ("600002", 60)],
            }.items():
                pd.DataFrame(values, columns=["code", "value"]).set_index("code").to_parquet(root / f"{period}.parquet")

            rows = load_symbol_financial_rows("600001", years=2, warehouse_dir=root)

        self.assertEqual([row["period"] for row in rows], ["2025A", "2026Q1"])
        self.assertEqual([row["row"]["value"] for row in rows], [30, 50])
        self.assertTrue(all(str(row["row"].name) == "600001" for row in rows))
