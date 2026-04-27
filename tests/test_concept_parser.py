import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "parse_concept_dataset.py"


class ConceptParserTests(unittest.TestCase):
    def test_builds_concept_dictionary_and_current_rows(self) -> None:
        from app.tdx.parsers import build_concept_datasets

        concept_text = "\n".join(
            [
                "0|000001|10001| 跨境支付CIPS , 不可减持(新规),跨境支付CIPS |0.00",
                "1|600000|10001| 人工智能， 华为概念 |0.00",
            ]
        )

        dictionary_rows, current_rows, snapshot_rows = build_concept_datasets(
            concept_text=concept_text,
            trading_day="2026-04-27",
            generated_at="2026-04-27T13:10:00+08:00",
            data_cutoff_time="2026-04-27T13:10:00+08:00",
        )

        self.assertEqual(4, len(dictionary_rows))
        self.assertEqual(4, len(current_rows))
        self.assertEqual(current_rows, snapshot_rows)

        first = current_rows[0]
        expected_id = hashlib.sha1("tdx_local:跨境支付CIPS".encode("utf-8")).hexdigest()
        self.assertEqual("dataset_stock_concept_current", first["dataset_name"])
        self.assertEqual("sz", first["market"])
        self.assertEqual("000001", first["symbol"])
        self.assertEqual("", first["stock_name"])
        self.assertEqual(expected_id, first["concept_id"])
        self.assertEqual("跨境支付CIPS", first["concept_name"])
        self.assertEqual(True, first["is_active"])
        self.assertEqual(1, first["concept_rank_in_stock"])
        self.assertEqual("跨境支付CIPS,不可减持(新规)", first["concept_list_raw"])
        self.assertEqual("concept_parser_v1", first["parser_version"])

        dictionary = {row["concept_name_normalized"]: row for row in dictionary_rows}
        self.assertEqual("2026-04-27", dictionary["人工智能"]["first_seen_date"])
        self.assertEqual("2026-04-27", dictionary["人工智能"]["last_seen_date"])
        self.assertEqual(True, dictionary["华为概念"]["is_active"])
        self.assertEqual([], dictionary["华为概念"]["alias_names"])

    def test_normalizes_and_deduplicates_concept_names(self) -> None:
        from app.tdx.parsers import normalize_concept_name, split_concept_names

        self.assertEqual("人工智能", normalize_concept_name("  人工智能  "))
        self.assertEqual(
            ["跨境支付CIPS", "不可减持(新规)", "华为概念"],
            split_concept_names(" 跨境支付CIPS ,不可减持(新规)，华为概念,跨境支付CIPS "),
        )

    def test_cli_writes_expected_json_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            concept_file = tmpdir_path / "extern_sys.txt"
            output_dir = tmpdir_path / "out"

            concept_file.write_text(
                "0|000001|10001|跨境支付CIPS,不可减持(新规)|0.00\n",
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--trading-day",
                    "2026-04-27",
                    "--extern-path",
                    str(concept_file),
                    "--output-dir",
                    str(output_dir),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(0, completed.returncode, completed.stderr)

            dictionary_path = output_dir / "dataset_concept_dictionary.json"
            current_path = output_dir / "dataset_stock_concept_current.json"
            snapshot_path = output_dir / "snapshot_stock_concept_membership.json"
            self.assertTrue(dictionary_path.exists())
            self.assertTrue(current_path.exists())
            self.assertTrue(snapshot_path.exists())

            dictionary_rows = json.loads(dictionary_path.read_text(encoding="utf-8"))
            snapshot_rows = json.loads(snapshot_path.read_text(encoding="utf-8"))
            self.assertEqual("dataset_concept_dictionary", dictionary_rows[0]["dataset_name"])
            self.assertEqual("snapshot_stock_concept_membership", snapshot_rows[0]["dataset_name"])


if __name__ == "__main__":
    unittest.main()
