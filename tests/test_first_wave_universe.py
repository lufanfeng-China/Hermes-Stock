import unittest
from scripts.build_first_wave_qfq_ohlcv import eligible


class FirstWaveUniverseTests(unittest.TestCase):
    def test_indices_do_not_get_relabelled_as_shenzhen_stocks(self):
        self.assertIsNone(eligible({'market': 'sh', 'symbol': '000001', 'stock_name': '上证指数'}))
        self.assertEqual(('sz', '000001', '平安银行'), eligible({'market': 'sz', 'symbol': '000001', 'stock_name': '平安银行'}))

    def test_common_a_share_universe_includes_beijing_and_excludes_risk_names(self):
        self.assertEqual(('bj', '920001', '示例股份'), eligible({'symbol': '920001', 'stock_name': '示例股份'}))
        for symbol, name in [('000001', 'ST示例'), ('600001', '*ST示例'), ('000001', 'S示例'), ('999999', '上证指数'), ('399001', '深证成指'), ('800001', '示例ETF')]:
            self.assertIsNone(eligible({'symbol': symbol, 'stock_name': name}))

if __name__ == '__main__':
    unittest.main()
