import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.data.rps_paths import resolve_rps_dataset_path


class RpsGenerationPathsTests(unittest.TestCase):
    def test_resolves_current_dataset_from_active_generation_manifest(self) -> None:
        with TemporaryDirectory() as temporary_dir:
            final_dir = Path(temporary_dir)
            generation = final_dir / "rps_generations" / "20260928-test"
            generation.mkdir(parents=True)
            current = generation / "dataset_stock_rps_current.json"
            current.write_text('[{"symbol": "600001"}]', encoding="utf-8")
            (final_dir / "dataset_stock_rps_manifest.json").write_text(
                json.dumps({"generation": "rps_generations/20260928-test"}), encoding="utf-8"
            )

            self.assertEqual(resolve_rps_dataset_path(final_dir, "dataset_stock_rps_current.json"), current)

    def test_uses_legacy_dataset_when_no_manifest_exists(self) -> None:
        with TemporaryDirectory() as temporary_dir:
            final_dir = Path(temporary_dir)
            legacy = final_dir / "dataset_stock_rps_history.json"
            legacy.write_text("[]", encoding="utf-8")

            self.assertEqual(resolve_rps_dataset_path(final_dir, legacy.name), legacy)

    def test_dashboard_current_reader_uses_manifest_generation(self) -> None:
        from app.search.index import load_rps_rows

        with TemporaryDirectory() as temporary_dir:
            final_dir = Path(temporary_dir)
            generation = final_dir / "rps_generations" / "20260928-test"
            generation.mkdir(parents=True)
            (generation / "dataset_stock_rps_current.json").write_text(
                '[{"market": "sh", "symbol": "600001", "rps_20": 99}]', encoding="utf-8"
            )
            (final_dir / "dataset_stock_rps_manifest.json").write_text(
                json.dumps({"generation": "rps_generations/20260928-test"}), encoding="utf-8"
            )

            self.assertEqual(load_rps_rows(final_dir), [{"market": "sh", "symbol": "600001", "rps_20": 99}])

    def test_history_api_reader_uses_manifest_generation(self) -> None:
        from app.data import rps_history

        with TemporaryDirectory() as temporary_dir:
            final_dir = Path(temporary_dir)
            generation = final_dir / "rps_generations" / "20260928-test"
            generation.mkdir(parents=True)
            (generation / "dataset_stock_rps_history.json").write_text(
                '[{"trading_day": "2026-07-31", "market": "sh", "symbol": "600001", "rps_20": 99}]',
                encoding="utf-8",
            )
            (final_dir / "dataset_stock_rps_manifest.json").write_text(
                json.dumps({"generation": "rps_generations/20260928-test"}), encoding="utf-8"
            )
            rps_history._load_rps_history_dataset.cache_clear()
            try:
                with patch.object(rps_history, "DERIVED_FINAL_DIR", final_dir):
                    payload = rps_history.load_stock_rps_history("600001")
            finally:
                rps_history._load_rps_history_dataset.cache_clear()

            self.assertEqual(payload["history"], [{"trading_day": "2026-07-31", "rps_20": 99, "rps_50": None, "rps_120": None, "rps_250": None}])
    def test_strategy_builder_history_reads_use_manifest_generation(self) -> None:
        import pandas as pd
        import scripts.build_stock_screener_strategies as builder

        with TemporaryDirectory() as temporary_dir:
            project = Path(temporary_dir)
            final_dir = project / "data/derived/datasets/final"
            generation = final_dir / "rps_generations" / "20260928-test"
            generation.mkdir(parents=True)
            rows = [
                {"trading_day": "2026-07-30", "market": "sh", "symbol": "600001", "rps_20": 80, "rps_50": 80, "rps_120": 80, "rps_250": 80},
                {"trading_day": "2026-07-31", "market": "sh", "symbol": "600001", "rps_20": 90, "rps_50": 90, "rps_120": 90, "rps_250": 90},
            ]
            (generation / "dataset_stock_rps_history.json").write_text(json.dumps(rows), encoding="utf-8")
            pd.DataFrame(rows).to_parquet(generation / "dataset_stock_rps_history.parquet", index=False)
            (final_dir / "dataset_stock_rps_manifest.json").write_text(
                json.dumps({"generation": "rps_generations/20260928-test"}), encoding="utf-8"
            )
            (final_dir / "dataset_stock_screener_strategies_2026-07-30.json").write_text(
                json.dumps([{"strategy": builder.STRATEGY_FIRST, "passed": True, "market": "sh", "symbol": "600001"}]),
                encoding="utf-8",
            )
            with patch.object(builder, "PROJECT_ROOT", project):
                past = builder._compute_past_days_rps(None, [], ndays=1, as_of="2026-07-31")
                self.assertEqual(past[0][("sh", "600001")]["rps_20"], 80)
                self.assertEqual(builder._load_past_rps_first_signals("2026-07-31"), {("sh", "600001")})


if __name__ == "__main__":
    unittest.main()