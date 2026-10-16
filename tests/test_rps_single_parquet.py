import importlib.util
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "refresh_rps_daily.py"


def load_refresh_module():
    spec = importlib.util.spec_from_file_location("refresh_rps_daily", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rps_row(day: str, market: str, symbol: str, value: float) -> dict[str, object]:
    return {
        "trading_day": day,
        "market": market,
        "symbol": symbol,
        "price_basis": "tdx_export_qfq",
        "rps_20": value,
        "rps_50": value,
        "rps_120": value,
        "rps_250": value,
    }


class SingleParquetRpsTests(unittest.TestCase):
    def test_search_latest_and_as_of_read_only_authoritative_parquet(self) -> None:
        from app.search import index

        with TemporaryDirectory() as temporary_dir:
            final_dir = Path(temporary_dir)
            parquet = final_dir / "dataset_stock_rps_history.parquet"
            rows = [
                rps_row("2026-07-30", "sh", "600001", 80),
                rps_row("2026-07-30", "sz", "000001", 70),
                rps_row("2026-07-31", "sh", "600001", 90),
            ]
            pd.DataFrame(rows).to_parquet(parquet, index=False)
            (final_dir / "dataset_stock_rps_current.json").write_text('[{"symbol":"legacy"}]', encoding="utf-8")
            (final_dir / "dataset_stock_rps_history.json").write_text('[{"symbol":"legacy"}]', encoding="utf-8")

            index.load_rps_rows.cache_clear()
            try:
                latest = index.load_rps_rows(final_dir)
                as_of = index.load_rps_rows_as_of("2026-07-30", final_dir)
            finally:
                index.load_rps_rows.cache_clear()

            self.assertEqual({row["symbol"] for row in latest}, {"600001"})
            self.assertEqual(latest[0]["trading_day"], "2026-07-31")
            self.assertEqual({(row["market"], row["symbol"]) for row in as_of}, {("sh", "600001"), ("sz", "000001")})
            self.assertTrue(all(row["trading_day"] == "2026-07-30" for row in as_of))

    def test_history_api_reads_parquet_not_legacy_json(self) -> None:
        from app.data import rps_history

        with TemporaryDirectory() as temporary_dir:
            final_dir = Path(temporary_dir)
            pd.DataFrame([rps_row("2026-07-31", "sh", "600001", 99)]).to_parquet(
                final_dir / "dataset_stock_rps_history.parquet", index=False
            )
            (final_dir / "dataset_stock_rps_history.json").write_text('[{"symbol":"600001","rps_20":1}]', encoding="utf-8")
            rps_history._load_rps_history_dataset.cache_clear()
            try:
                with patch.object(rps_history, "DERIVED_FINAL_DIR", final_dir):
                    payload = rps_history.load_stock_rps_history("600001")
            finally:
                rps_history._load_rps_history_dataset.cache_clear()
            self.assertEqual(payload["history"][0]["rps_20"], 99)

    def test_history_trading_days_are_read_from_authoritative_parquet(self) -> None:
        from app.data import rps_history

        with TemporaryDirectory() as temporary_dir:
            final_dir = Path(temporary_dir)
            pd.DataFrame([
                rps_row("2026-07-30", "sh", "600001", 80),
                rps_row("2026-07-31", "sh", "600001", 90),
                rps_row("2026-07-31", "sz", "000001", 70),
            ]).to_parquet(final_dir / "dataset_stock_rps_history.parquet", index=False)
            rps_history._load_rps_trading_days.cache_clear()
            try:
                with patch.object(rps_history, "DERIVED_FINAL_DIR", final_dir):
                    self.assertEqual(rps_history.load_rps_trading_days(), ["2026-07-30", "2026-07-31"])
            finally:
                rps_history._load_rps_trading_days.cache_clear()

    def test_pipeline_cache_clear_invalidates_cached_symbol_history(self) -> None:
        from app.data import rps_history
        from app.pipeline import runner

        with TemporaryDirectory() as temporary_dir:
            final_dir = Path(temporary_dir)
            parquet = final_dir / "dataset_stock_rps_history.parquet"
            rps_history._load_stock_rps_history_dataset.cache_clear()
            try:
                pd.DataFrame([rps_row("2026-07-30", "sh", "600001", 80)]).to_parquet(parquet, index=False)
                with patch.object(rps_history, "DERIVED_FINAL_DIR", final_dir):
                    self.assertEqual(rps_history.load_stock_rps_history("600001")["history"][-1]["rps_20"], 80)
                    pd.DataFrame([rps_row("2026-07-31", "sh", "600001", 99)]).to_parquet(parquet, index=False)
                    runner._clear_rps_cache()
                    refreshed = rps_history.load_stock_rps_history("600001")
                self.assertEqual(refreshed["history"][-1]["rps_20"], 99)
            finally:
                rps_history._load_stock_rps_history_dataset.cache_clear()

    def test_obsolete_rps_writers_are_retired(self) -> None:
        scripts_dir = PROJECT_ROOT / "scripts"
        for name in (
            "build_rps_history_adaptive.py",
            "build_rps_history_gapfill_2022.py",
            "check_and_build_rps_2020.py",
        ):
            self.assertFalse((scripts_dir / name).exists(), name)

    def test_refresh_atomically_replaces_only_authoritative_parquet(self) -> None:
        refresh = load_refresh_module()
        with TemporaryDirectory() as temporary_dir:
            final_dir = Path(temporary_dir)
            parquet = final_dir / "dataset_stock_rps_history.parquet"
            original = pd.DataFrame([rps_row("2026-07-30", "sh", "600001", 10)])
            original.to_parquet(parquet, index=False)

            summary = refresh.refresh_from_computed_rows(
                [rps_row("2026-07-31", "sh", "600001", 99)],
                parquet,
                {"2026-07-31": {("sh", "600001")}},
            )

            self.assertEqual(summary["latest_trading_day"], "2026-07-31")
            self.assertEqual(pd.read_parquet(parquet)["trading_day"].tolist(), ["2026-07-30", "2026-07-31"])
            self.assertFalse((final_dir / "dataset_stock_rps_current.json").exists())
            self.assertFalse((final_dir / "dataset_stock_rps_history.json").exists())
            self.assertFalse((final_dir / "dataset_stock_rps_manifest.json").exists())
            self.assertFalse((final_dir / "rps_generations").exists())

    def test_refresh_failed_atomic_swap_retains_old_parquet(self) -> None:
        refresh = load_refresh_module()
        with TemporaryDirectory() as temporary_dir:
            final_dir = Path(temporary_dir)
            parquet = final_dir / "dataset_stock_rps_history.parquet"
            pd.DataFrame([rps_row("2026-07-30", "sh", "600001", 10)]).to_parquet(parquet, index=False)
            before = parquet.read_bytes()
            real_replace = os.replace

            def fail_final_swap(source, destination):
                if Path(destination) == parquet:
                    raise OSError("injected final parquet swap failure")
                return real_replace(source, destination)

            with patch.object(refresh.os, "replace", side_effect=fail_final_swap):
                with self.assertRaisesRegex(OSError, "injected final parquet swap failure"):
                    refresh.refresh_from_computed_rows(
                        [rps_row("2026-07-31", "sh", "600001", 99)],
                        parquet,
                        {"2026-07-31": {("sh", "600001")}},
                    )
            self.assertEqual(parquet.read_bytes(), before)

    def test_one_time_migration_merges_newer_legacy_days_then_removes_legacy_files(self) -> None:
        refresh = load_refresh_module()
        with TemporaryDirectory() as temporary_dir:
            final_dir = Path(temporary_dir)
            parquet = final_dir / "dataset_stock_rps_history.parquet"
            legacy = final_dir / "dataset_stock_rps_history.json"
            current = final_dir / "dataset_stock_rps_current.json"
            pd.DataFrame([rps_row("2026-06-18", "sh", "600001", 10)]).to_parquet(parquet, index=False)
            legacy.write_text(json.dumps([rps_row("2026-07-31", "sh", "600001", 99)]), encoding="utf-8")
            current.write_text("[]", encoding="utf-8")
            legacy_current_parquet = final_dir / "dataset_stock_rps_current.parquet"
            legacy_current_parquet.write_bytes(b"obsolete placeholder")
            (final_dir / "rps_generations" / "obsolete").mkdir(parents=True)

            summary = refresh.migrate_legacy_history_if_newer(parquet, legacy)

            self.assertTrue(summary["migrated"])
            self.assertEqual(pd.read_parquet(parquet)["trading_day"].tolist(), ["2026-06-18", "2026-07-31"])
            self.assertFalse(legacy.exists())
            self.assertFalse(current.exists())
            self.assertFalse(legacy_current_parquet.exists())
            self.assertFalse((final_dir / "rps_generations").exists())

    def test_one_time_migration_promotes_active_generation_when_top_level_json_is_absent(self) -> None:
        """An interrupted generation publication must not discard its older history."""
        refresh = load_refresh_module()
        with TemporaryDirectory() as temporary_dir:
            final_dir = Path(temporary_dir)
            parquet = final_dir / "dataset_stock_rps_history.parquet"
            generation = final_dir / "rps_generations" / "20260928-active"
            generation.mkdir(parents=True)
            pd.DataFrame([
                rps_row("2026-06-18", "sh", "600001", 10),
                rps_row("2026-07-30", "sh", "600001", 80),
            ]).to_parquet(generation / parquet.name, index=False)
            # A subsequent partial single-Parquet write is newer, but has no old history.
            pd.DataFrame([rps_row("2026-07-31", "sh", "600001", 99)]).to_parquet(parquet, index=False)
            manifest = final_dir / "dataset_stock_rps_manifest.json"
            manifest.write_text(json.dumps({"generation": "rps_generations/20260928-active"}), encoding="utf-8")

            summary = refresh.migrate_legacy_history_if_newer(parquet)

            self.assertTrue(summary["migrated"])
            self.assertEqual(
                pd.read_parquet(parquet)["trading_day"].tolist(),
                ["2026-06-18", "2026-07-30", "2026-07-31"],
            )
            self.assertFalse(manifest.exists())
            self.assertFalse((final_dir / "rps_generations").exists())
            self.assertFalse((final_dir / "dataset_stock_rps_history.json").exists())
            self.assertFalse((final_dir / "dataset_stock_rps_current.json").exists())

    def test_one_time_migration_promotes_active_generation_history_json(self) -> None:
        refresh = load_refresh_module()
        with TemporaryDirectory() as temporary_dir:
            final_dir = Path(temporary_dir)
            parquet = final_dir / "dataset_stock_rps_history.parquet"
            generation = final_dir / "rps_generations" / "20260928-json-only"
            generation.mkdir(parents=True)
            (generation / "dataset_stock_rps_history.json").write_text(
                json.dumps([rps_row("2026-07-30", "sz", "000001", 88)]), encoding="utf-8"
            )
            (final_dir / "dataset_stock_rps_manifest.json").write_text(
                json.dumps({"generation": "rps_generations/20260928-json-only"}), encoding="utf-8"
            )

            refresh.migrate_legacy_history_if_newer(parquet)

            self.assertEqual(pd.read_parquet(parquet)["symbol"].tolist(), ["000001"])
            self.assertFalse((final_dir / "rps_generations").exists())

    def test_generation_artifacts_remain_if_migration_publication_fails(self) -> None:
        refresh = load_refresh_module()
        with TemporaryDirectory() as temporary_dir:
            final_dir = Path(temporary_dir)
            parquet = final_dir / "dataset_stock_rps_history.parquet"
            generation = final_dir / "rps_generations" / "20260928-active"
            generation.mkdir(parents=True)
            pd.DataFrame([rps_row("2026-07-30", "sh", "600001", 80)]).to_parquet(generation / parquet.name, index=False)
            manifest = final_dir / "dataset_stock_rps_manifest.json"
            manifest.write_text(json.dumps({"generation": "rps_generations/20260928-active"}), encoding="utf-8")

            with patch.object(refresh, "_atomic_replace_parquet", side_effect=OSError("injected migration failure")):
                with self.assertRaisesRegex(OSError, "injected migration failure"):
                    refresh.migrate_legacy_history_if_newer(parquet)

            self.assertTrue(manifest.exists())
            self.assertTrue(generation.exists())

    def test_normal_refresh_migrates_manifest_generation_before_qfq_freshness_gate(self) -> None:
        refresh = load_refresh_module()
        with TemporaryDirectory() as temporary_dir:
            final_dir = Path(temporary_dir)
            parquet = final_dir / "dataset_stock_rps_history.parquet"
            generation = final_dir / "rps_generations" / "20260928-active"
            generation.mkdir(parents=True)
            pd.DataFrame([rps_row("2026-07-30", "sh", "600001", 80)]).to_parquet(
                generation / parquet.name, index=False
            )
            manifest = final_dir / "dataset_stock_rps_manifest.json"
            manifest.write_text(json.dumps({"generation": "rps_generations/20260928-active"}), encoding="utf-8")

            observed: dict[str, object] = {}

            def observe_migration_then_stop(*_args: object) -> str:
                observed["manifest_exists"] = manifest.exists()
                observed["generation_exists"] = generation.exists()
                observed["days"] = pd.read_parquet(parquet)["trading_day"].tolist()
                return "2026-07-30"

            with (
                patch.object(refresh.sys, "argv", ["refresh_rps_daily.py", "--history-parquet", str(parquet)]),
                patch.object(refresh, "_latest_raw_trading_day", side_effect=observe_migration_then_stop),
                patch.object(refresh, "load_qfq_series", return_value={}),
                patch.object(refresh, "reference_qfq_calendar", return_value=["2026-07-30"]),
                patch.object(refresh, "compute_rps_rows", return_value=[rps_row("2026-07-30", "sh", "600001", 80)]),
                patch.object(
                    refresh, "eligible_universe_and_positions_by_day",
                    return_value=({"2026-07-30": {("sh", "600001")}}, {("sh", "600001"): {"2026-07-30": 250}}),
                ),
                patch.object(refresh, "refresh_from_computed_rows", return_value={"ok": True}),
            ):
                self.assertEqual(refresh.main(), 0)
            self.assertFalse(observed["manifest_exists"])
            self.assertFalse(observed["generation_exists"])
            self.assertEqual(observed["days"], ["2026-07-30"])


if __name__ == "__main__":
    unittest.main()
