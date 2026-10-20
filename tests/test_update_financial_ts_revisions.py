import importlib.util
from pathlib import Path
from unittest import TestCase, mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("update_financial_ts_under_test", ROOT / "scripts" / "update_financial_ts.py")
update = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(update)


class DetectFinancialRevisionTests(TestCase):
    def test_detects_later_announcement_for_existing_report_period(self):
        meta = {"stocks": {"688008": {"latest_period": "2026Q3", "periods": {"2026Q3": {"announce_date": 20261020}}}}}
        fake_zip = Path("/tmp/gpcw20260930.zip")
        record = {"report_date": 20260930, "announce_date": 20261031, "code": "688008"}
        class FakeDirectory:
            def glob(self, _pattern):
                return [fake_zip]
        with mock.patch.object(update, "TDX_CW", FakeDirectory()), \
             mock.patch.object(update, "read_stock_records_from_zip", return_value={"688008": record}):
            updates = update.detect_updates(meta)
        self.assertEqual([("688008", "2026Q3", 20260930, 20261031, record)], updates)
