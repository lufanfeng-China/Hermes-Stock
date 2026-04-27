import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "parse_industry_dataset.py"


class IndustryParserTests(unittest.TestCase):
    def test_builds_industry_current_and_snapshot_records(self) -> None:
        from app.tdx.parsers import build_industry_datasets

        industry_mapping_text = "\n".join(
            [
                "家电|881183|12|1|0|X24",
                "白色家电|881184|12|1|0|X2401",
                "空调|881185|12|1|1|X240101",
                "建筑|881405|12|1|0|X52",
                "基础建设|881407|12|1|0|X5202",
                "园林工程|881409|12|1|1|X520202",
            ]
        )
        stock_mapping_text = "\n".join(
            [
                "0|000333|T0401|||X240101",
                "1|600170|T110101|||X520202",
            ]
        )

        current_rows, snapshot_rows = build_industry_datasets(
            stock_mapping_text=stock_mapping_text,
            industry_code_text=industry_mapping_text,
            trading_day="2026-04-27",
            generated_at="2026-04-27T13:10:00+08:00",
            data_cutoff_time="2026-04-27T13:10:00+08:00",
        )

        self.assertEqual(2, len(current_rows))
        self.assertEqual(current_rows, snapshot_rows)

        first = current_rows[0]
        self.assertEqual("dataset_stock_industry_current", first["dataset_name"])
        self.assertEqual("2026-04-27", first["trading_day"])
        self.assertEqual("sz", first["market"])
        self.assertEqual("000333", first["symbol"])
        self.assertEqual("", first["stock_name"])
        self.assertEqual("T0401", first["industry_code_raw_t"])
        self.assertEqual("X240101", first["industry_code_raw_x"])
        self.assertEqual("X24", first["industry_level_1_code"])
        self.assertEqual("家电", first["industry_level_1_name"])
        self.assertEqual("X2401", first["industry_level_2_code"])
        self.assertEqual("白色家电", first["industry_level_2_name"])
        self.assertEqual("X240101", first["industry_level_3_code"])
        self.assertEqual("空调", first["industry_level_3_name"])
        self.assertEqual("tdx_x_tree", first["industry_source"])
        self.assertEqual("tdx_local", first["source"])
        self.assertEqual("T0002/hq_cache/tdxhy.cfg", first["source_file"])
        self.assertEqual("industry_parser_v1", first["parser_version"])
        self.assertEqual(1.0, first["mapping_confidence"])
        self.assertEqual("passed", first["validation_status"])

        second = current_rows[1]
        self.assertEqual("sh", second["market"])
        self.assertEqual("建筑", second["industry_level_1_name"])
        self.assertEqual("基础建设", second["industry_level_2_name"])
        self.assertEqual("园林工程", second["industry_level_3_name"])

    def test_derives_hierarchy_names_by_truncating_x_code(self) -> None:
        from app.tdx.parsers import derive_industry_hierarchy, parse_industry_code_map

        code_map = parse_industry_code_map(
            "\n".join(
                [
                    "家电|881183|12|1|0|X24",
                    "白色家电|881184|12|1|0|X2401",
                    "空调|881185|12|1|1|X240101",
                ]
            )
        )

        hierarchy = derive_industry_hierarchy("X240101", code_map)

        self.assertEqual(
            {
                "industry_level_1_code": "X24",
                "industry_level_1_name": "家电",
                "industry_level_2_code": "X2401",
                "industry_level_2_name": "白色家电",
                "industry_level_3_code": "X240101",
                "industry_level_3_name": "空调",
            },
            hierarchy,
        )

    def test_cli_writes_expected_json_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            stock_mapping = tmpdir_path / "tdxhy.cfg"
            industry_codes = tmpdir_path / "tdxzs3.cfg"
            output_dir = tmpdir_path / "out"

            stock_mapping.write_text("0|000333|T0401|||X240101\n", encoding="utf-8")
            industry_codes.write_text(
                "家电|881183|12|1|0|X24\n白色家电|881184|12|1|0|X2401\n空调|881185|12|1|1|X240101\n",
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--trading-day",
                    "2026-04-27",
                    "--tdxhy-path",
                    str(stock_mapping),
                    "--tdxzs3-path",
                    str(industry_codes),
                    "--output-dir",
                    str(output_dir),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, completed.returncode, completed.stderr)

            current_path = output_dir / "dataset_stock_industry_current.json"
            snapshot_path = output_dir / "snapshot_stock_industry_membership.json"
            self.assertTrue(current_path.exists())
            self.assertTrue(snapshot_path.exists())

            current_rows = json.loads(current_path.read_text(encoding="utf-8"))
            snapshot_rows = json.loads(snapshot_path.read_text(encoding="utf-8"))
            self.assertEqual("dataset_stock_industry_current", current_rows[0]["dataset_name"])
            self.assertEqual("snapshot_stock_industry_membership", snapshot_rows[0]["dataset_name"])


if __name__ == "__main__":
    unittest.main()
