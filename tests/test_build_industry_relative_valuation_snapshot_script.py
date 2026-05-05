import contextlib
import io
import unittest
from pathlib import Path
from unittest import mock


class BuildIndustryRelativeValuationSnapshotScriptTests(unittest.TestCase):
    def test_main_prints_progress_and_member_valuation_summary(self) -> None:
        from scripts import build_industry_relative_valuation_snapshot as script

        def fake_write(*, progress_callback=None, reuse_existing_complete=False, continue_on_error=True):
            self.assertFalse(reuse_existing_complete)
            self.assertTrue(continue_on_error)
            self.assertIsNotNone(progress_callback)
            progress_callback({"event": "start", "total_industries": 1})
            progress_callback({
                "event": "industry_start",
                "index": 1,
                "total_industries": 1,
                "industry_level_2_name": "消费电子",
            })
            progress_callback({
                "event": "industry_done",
                "index": 1,
                "total_industries": 1,
                "industry_level_2_name": "消费电子",
                "member_valuation_row_count": 104,
                "percentile_sample_count": 88,
            })
            progress_callback({
                "event": "complete",
                "total_industries": 1,
                "success_count": 1,
                "failure_count": 0,
                "skipped_count": 0,
                "total_member_valuation_rows": 104,
            })
            return Path("/tmp/dataset_industry_valuation_current.json")

        output = io.StringIO()
        with mock.patch.object(script, "write_current_industry_snapshots", side_effect=fake_write):
            with contextlib.redirect_stdout(output):
                script.main([])

        text = output.getvalue()
        self.assertIn("开始构建行业相对估值快照（含同业估值表 member_valuation_rows）", text)
        self.assertIn("[1/1] 消费电子", text)
        self.assertIn("member_valuation_rows=104", text)
        self.assertIn("完成：成功 1/1，跳过 0，失败 0，同业估值行 104", text)
        self.assertIn("/tmp/dataset_industry_valuation_current.json", text)

    def test_main_allows_reusing_existing_complete_industries(self) -> None:
        from scripts import build_industry_relative_valuation_snapshot as script

        captured = {}

        def fake_write(*, progress_callback=None, reuse_existing_complete=False, continue_on_error=True):
            captured["reuse_existing_complete"] = reuse_existing_complete
            captured["continue_on_error"] = continue_on_error
            return Path("/tmp/current.json")

        with mock.patch.object(script, "write_current_industry_snapshots", side_effect=fake_write):
            with contextlib.redirect_stdout(io.StringIO()):
                script.main(["--reuse-existing-complete", "--fail-fast"])

        self.assertTrue(captured["reuse_existing_complete"])
        self.assertFalse(captured["continue_on_error"])


if __name__ == "__main__":
    unittest.main()
