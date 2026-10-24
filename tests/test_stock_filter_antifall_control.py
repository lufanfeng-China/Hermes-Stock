import unittest
from pathlib import Path
from html.parser import HTMLParser

ROOT = Path(__file__).resolve().parents[1]

class Inputs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inputs = {}
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'input':
            self.inputs[attrs.get('name')] = attrs

class AntiFallControlTests(unittest.TestCase):
    def test_total_excess_range_is_below_win_rate_and_allows_negative_values(self):
        html = (ROOT / 'web/stock-filter.html').read_text()
        parser = Inputs()
        parser.feed(html)
        for suffix in ('min', 'max'):
            control = parser.inputs.get('down_market_total_excess_pp_20_' + suffix)
            self.assertIsNotNone(control)
            self.assertEqual(control['type'], 'number')
            self.assertNotIn('min', control)
        self.assertLess(html.index('name="down_market_win_rate_20_max"'), html.index('name="down_market_total_excess_pp_20_min"'))
        self.assertIn('抗跌超额总数（pp）', html)

if __name__ == '__main__':
    unittest.main()
