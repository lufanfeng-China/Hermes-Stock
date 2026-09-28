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


def qfq_frame(days: list[str]) -> pd.DataFrame:
    return pd.DataFrame({"close": list(range(1, len(days) + 1))}, index=pd.to_datetime(days))


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


class RefreshRpsDailyTests(unittest.TestCase):
    def test_rejects_refresh_when_qfq_does_not_cover_latest_raw_day(self) -> None:
        refresh = load_refresh_module()

        with self.assertRaisesRegex(
            refresh.QfqCoverageError,
            r"QFQ export data is stale.*2026-09-24.*2026-07-31.*export QFQ data",
        ):
            refresh.require_qfq_covers_raw("2026-09-24", "2026-07-31")

    def test_uses_declared_reference_calendar_not_longest_stale_calendar(self) -> None:
        refresh = load_refresh_module()
        dates = pd.date_range("2025-01-01", periods=253, freq="B")
        stale_dates = dates[:-1].strftime("%Y-%m-%d").tolist()
        fresh_short_dates = dates[-251:].strftime("%Y-%m-%d").tolist()
        qfq_series = {
            ("sh", "601600"): qfq_frame(stale_dates),
            ("sz", "000001"): qfq_frame(fresh_short_dates),
        }

        with self.assertRaisesRegex(refresh.QfqCoverageError, r"reference QFQ calendar.*601600.*stale"):
            refresh.reference_qfq_calendar(qfq_series, "601600", dates[-1].date().isoformat())

    def test_rejects_target_day_with_insufficient_eligible_qfq_universe(self) -> None:
        refresh = load_refresh_module()
        dates = pd.date_range("2025-01-01", periods=251, freq="B").strftime("%Y-%m-%d").tolist()
        qfq_series = {("sh", "601600"): qfq_frame(dates)}
        reference_dates = refresh.reference_qfq_calendar(qfq_series, "601600", dates[-1])

        with self.assertRaisesRegex(refresh.QfqCoverageError, r"QFQ eligible universe.*at least 2"):
            refresh.compute_rps_rows(qfq_series, 1, reference_dates)

    def test_refresh_replaces_overlapping_parquet_days_without_duplicates(self) -> None:
        refresh = load_refresh_module()
        with TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            history_json = root / "dataset_stock_rps_history.json"
            history_parquet = root / "dataset_stock_rps_history.parquet"
            current_json = root / "dataset_stock_rps_current.json"
            existing = pd.DataFrame([
                rps_row("2026-07-29", "sh", "600001", 11.0),
                rps_row("2026-07-30", "sh", "600001", 12.0),
            ])
            existing.to_parquet(history_parquet, index=False)
            computed = [
                rps_row("2026-07-30", "sh", "600001", 88.0),
                rps_row("2026-07-31", "sh", "600001", 99.0),
            ]

            summary = refresh.refresh_from_computed_rows(
                computed, history_json, history_parquet, current_json,
                {"2026-07-30": {("sh", "600001")}, "2026-07-31": {("sh", "600001")}},
            )

            manifest = json.loads((root / "dataset_stock_rps_manifest.json").read_text(encoding="utf-8"))
            generation_dir = root / manifest["generation"]
            merged = pd.read_parquet(generation_dir / "dataset_stock_rps_history.parquet").sort_values("trading_day")
            self.assertEqual(summary["latest_trading_day"], "2026-07-31")
            self.assertEqual(merged["trading_day"].tolist(), ["2026-07-29", "2026-07-30", "2026-07-31"])
            self.assertEqual(len(merged), 3)
            self.assertEqual(float(merged.loc[merged["trading_day"] == "2026-07-30", "rps_20"].iloc[0]), 88.0)
            self.assertEqual(
                json.loads((generation_dir / "dataset_stock_rps_history.json").read_text(encoding="utf-8")),
                merged.to_dict(orient="records"),
            )
            self.assertFalse(history_json.exists())

    def test_refuses_overlap_replacement_when_computed_universe_is_incomplete(self) -> None:
        refresh = load_refresh_module()
        with TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            history_json = root / "dataset_stock_rps_history.json"
            history_parquet = root / "dataset_stock_rps_history.parquet"
            current_json = root / "dataset_stock_rps_current.json"
            original = pd.DataFrame([
                rps_row("2026-07-30", "sh", "600001", 10.0),
                rps_row("2026-07-30", "sz", "000001", 20.0),
            ])
            original.to_parquet(history_parquet, index=False)
            before = history_parquet.read_bytes()

            with self.assertRaisesRegex(ValueError, r"incomplete eligible universe.*2026-07-30"):
                refresh.refresh_from_computed_rows(
                    [rps_row("2026-07-30", "sh", "600001", 88.0)],
                    history_json, history_parquet, current_json,
                    {"2026-07-30": {("sh", "600001"), ("sz", "000001")}},
                )

            self.assertEqual(history_parquet.read_bytes(), before)
            self.assertFalse(history_json.exists())
            self.assertFalse(current_json.exists())

    def test_refuses_overlap_replacement_when_computed_drops_existing_member(self) -> None:
        refresh = load_refresh_module()
        with TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            history_json = root / "dataset_stock_rps_history.json"
            history_parquet = root / "dataset_stock_rps_history.parquet"
            current_json = root / "dataset_stock_rps_current.json"
            original = pd.DataFrame([
                rps_row("2026-07-30", "sh", "600001", 10.0),
                rps_row("2026-07-30", "sz", "000001", 20.0),
            ])
            original.to_parquet(history_parquet, index=False)

            with self.assertRaisesRegex(ValueError, r"drops existing historical members.*2026-07-30.*sz:000001"):
                refresh.refresh_from_computed_rows(
                    [rps_row("2026-07-30", "sh", "600001", 88.0)],
                    history_json, history_parquet, current_json,
                    {"2026-07-30": {("sh", "600001")}},
                )

            self.assertEqual(pd.read_parquet(history_parquet).to_dict(orient="records"), original.to_dict(orient="records"))

    def test_generation_manifest_publication_keeps_active_generation_on_interrupted_build(self) -> None:
        refresh = load_refresh_module()
        with TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            history_json = root / "dataset_stock_rps_history.json"
            history_parquet = root / "dataset_stock_rps_history.parquet"
            current_json = root / "dataset_stock_rps_current.json"
            original = [rps_row("2026-07-30", "sh", "600001", 10.0)]
            pd.DataFrame(original).to_parquet(history_parquet, index=False)
            history_json.write_text(json.dumps(original), encoding="utf-8")
            current_json.write_text(json.dumps(original), encoding="utf-8")
            refresh.refresh_from_computed_rows(
                [rps_row("2026-07-30", "sh", "600001", 20.0)], history_json, history_parquet, current_json,
                {"2026-07-30": {("sh", "600001")}},
            )
            manifest_path = root / "dataset_stock_rps_manifest.json"
            before = manifest_path.read_bytes()
            real_replace = os.replace

            def fail_manifest_swap(source: str | Path, destination: str | Path) -> None:
                if Path(destination) == manifest_path:
                    raise OSError("injected manifest swap failure")
                real_replace(source, destination)

            with patch.object(refresh.os, "replace", side_effect=fail_manifest_swap):
                with self.assertRaisesRegex(OSError, "injected manifest swap failure"):
                    refresh.refresh_from_computed_rows(
                        [rps_row("2026-07-31", "sh", "600001", 99.0)],
                        history_json, history_parquet, current_json,
                        {"2026-07-31": {("sh", "600001")}},
                    )

            self.assertEqual(manifest_path.read_bytes(), before)
            manifest = json.loads(before)
            active = root / manifest["generation"]
            self.assertEqual(
                json.loads((active / "dataset_stock_rps_current.json").read_text(encoding="utf-8")),
                [rps_row("2026-07-30", "sh", "600001", 20.0)],
            )

    def test_daily_pipeline_uses_single_rps_refresh_command(self) -> None:
        from app.pipeline.commands import _data_update_commands

        commands = dict(_data_update_commands(trading_day=None))
        self.assertIn("refresh_rps_daily", commands)
        self.assertNotIn("build_rps_history", commands)
        self.assertNotIn("update_rps_current", commands)
        self.assertTrue(commands["refresh_rps_daily"][1].endswith("scripts/refresh_rps_daily.py"))

    def test_refresh_current_rows_match_latest_computed_day(self) -> None:
        refresh = load_refresh_module()
        with TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            history_json = root / "dataset_stock_rps_history.json"
            history_parquet = root / "dataset_stock_rps_history.parquet"
            current_json = root / "dataset_stock_rps_current.json"
            computed = [
                rps_row("2026-07-30", "sh", "600001", 75.0),
                rps_row("2026-07-31", "sh", "600001", 90.0),
                rps_row("2026-07-31", "sz", "000001", 80.0),
            ]

            refresh.refresh_from_computed_rows(
                computed, history_json, history_parquet, current_json,
                {"2026-07-30": {("sh", "600001")}, "2026-07-31": {("sh", "600001"), ("sz", "000001")}},
            )

            manifest = json.loads((root / "dataset_stock_rps_manifest.json").read_text(encoding="utf-8"))
            current = json.loads((root / manifest["generation"] / "dataset_stock_rps_current.json").read_text(encoding="utf-8"))
            self.assertEqual(current, computed[1:])
            self.assertTrue(all(row["trading_day"] == "2026-07-31" for row in current))


if __name__ == "__main__":
    unittest.main()
