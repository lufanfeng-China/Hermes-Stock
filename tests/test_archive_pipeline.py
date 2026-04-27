import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.archive import jobs
from scripts import archive_daily


def _build_context(project_root: Path, trading_day: str = "2026-04-24") -> archive_daily.ArchiveContext:
    archive_root = project_root / "data" / "archive" / f"trading_day={trading_day}"
    started_at = "2026-04-24T15:30:00+08:00"
    return archive_daily.ArchiveContext(
        trading_day=trading_day,
        force_rerun=True,
        rerun_reason="archive-industry-concept",
        dry_run=True,
        project_root=project_root,
        archive_root=archive_root,
        manifests_dir=archive_root / "manifests",
        lock_path=archive_root / ".lock",
        manifest_path=archive_root / "manifests" / "day_manifest.json",
        success_marker_path=archive_root / "_SUCCESS.json",
        failed_marker_path=archive_root / "_FAILED.json",
        archive_revision=1,
        run_id="archive_20260424_01",
        started_at=started_at,
        generated_at=started_at,
        data_cutoff_time="2026-04-24T15:00:00+08:00",
    )


def _write_tdx_source_files(root: Path) -> tuple[Path, Path, Path]:
    source_dir = root / "tdx"
    source_dir.mkdir(parents=True, exist_ok=True)

    tdxhy_path = source_dir / "tdxhy.cfg"
    tdxhy_path.write_text("0|000333|T0401|||X240101\n", encoding="utf-8")

    tdxzs3_path = source_dir / "tdxzs3.cfg"
    tdxzs3_path.write_text(
        "家电|881183|12|1|0|X24\n白色家电|881184|12|1|0|X2401\n空调|881185|12|1|1|X240101\n",
        encoding="utf-8",
    )

    extern_path = source_dir / "extern_sys.txt"
    extern_path.write_text("0|000333|10001|智能家居,家电|0.00\n", encoding="utf-8")
    return tdxhy_path, tdxzs3_path, extern_path


def _stub_final_inputs(trading_day: str) -> dict[str, object]:
    return {
        "source_summary": {
            "primary_source": "local_tongdaxin_minute",
            "secondary_sources": [],
            "data_status": "final",
            "price_mode_default": "raw",
            "intraday_base_interval": "1m",
            "derived_base_interval": "1m",
            "fallback_enabled": False,
        },
        "versions": {
            "api_version": "v1",
            "schema_version": "1.0.0",
            "rule_version": "1.0.0",
            "derivation_version": "real-volume-window-v1",
            "data_pipeline_version": "1.0.0",
            "model_version": "unittest-stub",
        },
        "notes": [],
        "exception_summary": {
            "has_exceptions": False,
            "exception_count": 0,
            "retryable_count": 0,
            "non_retryable_count": 0,
            "top_errors": [],
        },
        "minute_data": {
            "market": "sh",
            "symbol": "601600",
            "trading_day": trading_day,
            "row_count": 2,
            "first_timestamp": f"{trading_day} 09:31:00",
            "last_timestamp": f"{trading_day} 14:30:00",
            "rows": [
                {
                    "timestamp": f"{trading_day} 09:31:00",
                    "open": 1.0,
                    "high": 1.0,
                    "low": 1.0,
                    "close": 1.0,
                    "amount": 100.0,
                    "volume": 10,
                },
                {
                    "timestamp": f"{trading_day} 14:30:00",
                    "open": 1.0,
                    "high": 1.0,
                    "low": 1.0,
                    "close": 1.0,
                    "amount": 200.0,
                    "volume": 20,
                },
            ],
        },
    }


class ArchivePipelineTests(unittest.TestCase):
    def test_build_final_outputs_adds_industry_and_concept_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            ctx = _build_context(project_root)
            archive_daily.initialize_archive_dirs(ctx)
            tdxhy_path, tdxzs3_path, extern_path = _write_tdx_source_files(project_root)

            with (
                mock.patch.object(jobs, "TDXHY_PATH", tdxhy_path),
                mock.patch.object(jobs, "TDXZS3_PATH", tdxzs3_path),
                mock.patch.object(jobs, "EXTERN_SYS_PATH", extern_path),
            ):
                datasets = jobs.build_final_datasets(ctx, [])
                snapshots = jobs.build_final_snapshots(ctx, datasets)

            dataset_names = {item["dataset_name"] for item in datasets}
            self.assertTrue(
                {
                    "dataset_stock_candidate_pool",
                    "dataset_stock_industry_current",
                    "dataset_concept_dictionary",
                    "dataset_stock_concept_current",
                }.issubset(dataset_names)
            )

            snapshot_names = {item["dataset_name"] for item in snapshots}
            self.assertTrue(
                {
                    "snapshot_market_overview",
                    "snapshot_stock_industry_membership",
                    "snapshot_stock_concept_membership",
                }.issubset(snapshot_names)
            )

            industry_dataset = next(item for item in datasets if item["dataset_name"] == "dataset_stock_industry_current")
            concept_dataset = next(item for item in datasets if item["dataset_name"] == "dataset_stock_concept_current")
            industry_snapshot = next(item for item in snapshots if item["dataset_name"] == "snapshot_stock_industry_membership")
            concept_snapshot = next(item for item in snapshots if item["dataset_name"] == "snapshot_stock_concept_membership")

            self.assertEqual(
                "data/derived/datasets/final/dataset_stock_industry_current.parquet",
                industry_dataset["path"],
            )
            self.assertEqual(
                "data/derived/datasets/final/dataset_stock_concept_current.parquet",
                concept_dataset["path"],
            )
            self.assertEqual(
                f"data/archive/trading_day={ctx.trading_day}/snapshots/snapshot_stock_industry_membership.parquet",
                industry_snapshot["path"],
            )
            self.assertEqual(
                f"data/archive/trading_day={ctx.trading_day}/snapshots/snapshot_stock_concept_membership.parquet",
                concept_snapshot["path"],
            )

            industry_rows = json.loads((project_root / "data/derived/datasets/final/dataset_stock_industry_current.json").read_text(encoding="utf-8"))
            concept_rows = json.loads((project_root / f"data/archive/trading_day={ctx.trading_day}/snapshots/snapshot_stock_concept_membership.json").read_text(encoding="utf-8"))
            self.assertEqual("dataset_stock_industry_current", industry_rows[0]["dataset_name"])
            self.assertEqual("snapshot_stock_concept_membership", concept_rows[0]["dataset_name"])
            self.assertIn("concept_filter_version", concept_rows[0])
            self.assertIn("concept_filter_bucket", concept_rows[0])
            self.assertIn("concept_filter_decision", concept_rows[0])
            self.assertIn("concept_filter_rule_id", concept_rows[0])

    def test_execute_pipeline_registers_new_datasets_and_stock_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            ctx = _build_context(project_root)
            tdxhy_path, tdxzs3_path, extern_path = _write_tdx_source_files(project_root)

            with (
                mock.patch.object(archive_daily, "load_final_inputs", return_value=_stub_final_inputs(ctx.trading_day)),
                mock.patch.object(jobs, "TDXHY_PATH", tdxhy_path),
                mock.patch.object(jobs, "TDXZS3_PATH", tdxzs3_path),
                mock.patch.object(jobs, "EXTERN_SYS_PATH", extern_path),
            ):
                manifest = archive_daily.execute_pipeline(ctx)

            dataset_names = {item["dataset_name"] for item in manifest["datasets_included"]}
            self.assertIn("dataset_stock_industry_current", dataset_names)
            self.assertIn("dataset_concept_dictionary", dataset_names)
            self.assertIn("dataset_stock_concept_current", dataset_names)
            self.assertIn("snapshot_stock_industry_membership", dataset_names)
            self.assertIn("snapshot_stock_concept_membership", dataset_names)
            self.assertEqual("available", manifest["snapshot_summary"]["stock_snapshot"])
            self.assertEqual("passed", manifest["validation_summary"]["overall_status"])


if __name__ == "__main__":
    unittest.main()
