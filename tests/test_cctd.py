from __future__ import annotations

import unittest

from futures_intel.sources.cctd import parse_cctd_homepage


class CctdParserTest(unittest.TestCase):
    def test_parses_prices_without_unit_text(self) -> None:
        source = "<div>秦皇岛|986|1.0%|09-09</div><div>综合交易5500|891|0.7%|09-09</div>"
        rows = parse_cctd_homepage(source, quote_date="2026-09-10")
        by_name = {row["benchmark"]: row for row in rows}
        self.assertEqual(986.0, by_name["秦皇岛"]["price"])
        self.assertEqual("2026-09-09", by_name["秦皇岛"]["quote_date"])
        self.assertEqual(891.0, by_name["综合交易5500"]["price"])


if __name__ == "__main__":
    unittest.main()
