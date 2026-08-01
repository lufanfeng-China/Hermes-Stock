import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, "/home/lufanfeng/Project-Hermes-Stock")
from app.tdx.qfq_kline import align_qfq_signal_with_raw_execution, load_tdx_qfq_daily


class TdxQfqKlineTests(unittest.TestCase):
    def _write_export(self, directory: Path, name: str = "SH#688019.txt") -> Path:
        path = directory / name
        path.write_text(
            "688019 澜起科技 日线 前复权\n"
            "日期\t开盘\t最高\t最低\t收盘\t成交量\t成交额\n"
            "2026/04/10\t190.00\t195.00\t189.00\t194.00\t1000\t194000.00\n"
            "2026/04/13\t195.00\t200.00\t194.00\t196.00\t1100\t215600.00\n"
            "#数据来源:通达信\n",
            encoding="gb18030",
        )
        return path

    def test_loads_front_adjusted_ohlcv_from_tdx_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write_export(Path(tmp))

            frame = load_tdx_qfq_daily("688019", export_dir=Path(tmp))

        self.assertEqual(pd.Timestamp("2026-04-10"), frame.index[0])
        self.assertEqual(pd.Timestamp("2026-04-13"), frame.index[-1])
        self.assertEqual(["open", "high", "low", "close", "volume", "amount"], list(frame.columns))
        self.assertAlmostEqual(196.0, frame.loc[pd.Timestamp("2026-04-13"), "close"])
        self.assertAlmostEqual(1100.0, frame.loc[pd.Timestamp("2026-04-13"), "volume"])
        self.assertEqual("tdx_export_qfq", frame.attrs["price_basis"])

    def test_uses_sh_sz_and_bj_filename_prefixes(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self._write_export(directory, "SZ#000001.txt")
            self._write_export(directory, "BJ#920001.txt")

            self.assertEqual(2, len(load_tdx_qfq_daily("000001", export_dir=directory)))
            self.assertEqual(2, len(load_tdx_qfq_daily("920001", export_dir=directory)))

    def test_aligns_qfq_signal_prices_with_raw_execution_prices(self):
        dates = pd.to_datetime(["2026-04-10", "2026-04-13", "2026-04-14"])
        raw = pd.DataFrame(
            {"open": [250.0, 260.0, 270.0], "high": [251.0, 261.0, 271.0],
             "low": [249.0, 259.0, 269.0], "close": [250.0, 255.0, 265.0],
             "volume": [1.0, 2.0, 3.0], "amount": [250.0, 510.0, 795.0]},
            index=dates,
        )
        qfq = pd.DataFrame(
            {"open": [190.0, 195.0], "high": [191.0, 200.0], "low": [189.0, 194.0],
             "close": [194.0, 196.0], "volume": [1.0, 2.0], "amount": [194.0, 392.0]},
            index=dates[:2],
        )

        bars = align_qfq_signal_with_raw_execution(raw, qfq)

        self.assertEqual(list(dates[:2]), list(bars.index))
        self.assertEqual(195.0, bars.loc[dates[1], "signal_open"])
        self.assertEqual(200.0, bars.loc[dates[1], "signal_high"])
        self.assertEqual(194.0, bars.loc[dates[1], "signal_low"])
        self.assertEqual(196.0, bars.loc[dates[1], "signal_close"])
        self.assertEqual(2.0, bars.loc[dates[1], "signal_volume"])
        self.assertEqual(260.0, bars.loc[dates[1], "raw_open"])
        self.assertEqual(255.0, bars.loc[dates[1], "raw_close"])
        self.assertEqual("tdx_export_qfq", bars.attrs["signal_price_basis"])
        self.assertEqual("tdx_raw", bars.attrs["execution_price_basis"])


if __name__ == "__main__":
    unittest.main()
