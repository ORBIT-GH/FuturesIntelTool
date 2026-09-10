from __future__ import annotations

import unittest
from datetime import date

from futures_intel.sources.jiaoyifamen import (
    parse_basis_payload,
    parse_position_payload,
)
from futures_intel.sources.sina import (
    candidate_contracts,
    choose_main_contract,
    normalize_contract_code,
    parse_daily_kline_jsonp,
    parse_sina_quotes,
)


QUOTE_FIXTURE = '''
var hq_str_nf_SH2610="烧碱2610,103734,1931.000,1973.000,1919.000,0.000,1953.000,1954.000,1954.000,1926.000,1944.000,15,1,24908.000,77273,郑,烧碱,2026-09-10,0";
var hq_str_nf_SH2611="烧碱2611,103734,1969.000,2022.000,1953.000,0.000,2000.000,2001.000,2001.000,1963.000,1973.000,242,150,234242.000,467719,郑,烧碱,2026-09-10,1";
var hq_str_nf_SH2701="烧碱2701,103734,2048.000,2103.000,2034.000,0.000,2082.000,2084.000,2083.000,2046.000,2056.000,60,40,71827.000,59410,郑,烧碱,2026-09-10,0";
'''

KLINE_FIXTURE = '''
var _X = ([{"d":"2026-09-08","o":"1940","h":"1960","l":"1920","c":"1950","v":"100","p":"200","s":"1945"},
{"d":"2026-09-09","o":"1950","h":"2020","l":"1940","c":"2000","v":"150","p":"220","s":"1970"}]);
'''

POSITION_FIXTURE = {
    "code": 200,
    "message": "成功",
    "data": {
        "futureName": "烧碱611",
        "instrument": "SH611",
        "long_rank_table": [
            {
                "day": "2026-09-09 00:00:00",
                "rank": 1,
                "memberName": "国泰君安",
                "indicator": 1000,
                "indicatorIncrease": 20,
            }
        ],
        "short_rank_table": [
            {
                "day": "2026-09-09 00:00:00",
                "rank": 1,
                "memberName": "中信期货",
                "indicator": 1200,
                "indicatorIncrease": -10,
            }
        ],
        "net_long_rank_table": [
            {
                "day": "2026-09-09 00:00:00",
                "rank": 1,
                "memberName": "方正中期",
                "indicator": 800,
                "indicatorIncrease": 30,
            }
        ],
        "net_short_rank_table": [
            {
                "day": "2026-09-09 00:00:00",
                "rank": 1,
                "memberName": "创元期货",
                "indicator": 900,
                "indicatorIncrease": 40,
            }
        ],
    },
}


class SourceParserTest(unittest.TestCase):
    def test_sina_quote_parser(self) -> None:
        quotes = parse_sina_quotes(QUOTE_FIXTURE)
        self.assertEqual(3, len(quotes))
        by_contract = {quote.contract: quote for quote in quotes}
        self.assertEqual(234242.0, by_contract["SH2611"].open_interest)
        self.assertEqual(467719.0, by_contract["SH2611"].volume)
        self.assertEqual("2026-09-10", by_contract["SH2611"].trading_date)

    def test_choose_main_contract_uses_oi_then_volume(self) -> None:
        rows = choose_main_contract(parse_sina_quotes(QUOTE_FIXTURE), "SH")
        self.assertEqual("SH2611", rows[0]["contract"])
        self.assertEqual(1, rows[0]["is_main"])
        self.assertEqual(2, rows[1]["rank"])

    def test_candidate_and_normalize_contract(self) -> None:
        contracts = candidate_contracts("SH", date(2026, 9, 10), months_ahead=3)
        self.assertEqual(
            ["SH2609", "SH2610", "SH2611", "SH2612"], contracts
        )
        self.assertEqual("SH2701", normalize_contract_code("SH701", "2026-09-10"))
        self.assertEqual("SH2611", normalize_contract_code("SH611", "2026-09-10"))

    def test_daily_kline_parser_computes_previous_settlement(self) -> None:
        rows = parse_daily_kline_jsonp(
            KLINE_FIXTURE, product_code="SH", contract="SH2611"
        )
        self.assertEqual(2, len(rows))
        self.assertEqual(1970.0, rows[1]["settlement"])
        self.assertEqual(1945.0, rows[1]["previous_settlement"])

    def test_position_parser(self) -> None:
        parsed = parse_position_payload(POSITION_FIXTURE, product_code="SH")
        self.assertEqual("SH2611", parsed["contract"])
        self.assertEqual("2026-09-09", parsed["trading_date"])
        self.assertEqual(1000.0, parsed["long_total"])
        self.assertEqual(1200.0, parsed["short_total"])
        self.assertEqual(-200.0, parsed["net_total"])
        self.assertEqual(4, len(parsed["positions"]))

    def test_basis_parser_uses_category_and_price_value(self) -> None:
        fixture = {
            "code": 200,
            "data": {
                "category": ["2026-09-08", "2026-09-09"],
                "basisValue": [10.5, -4.29],
                "priceValue": [1940.0, 1970.0],
            },
        }
        rows = parse_basis_payload(
            fixture, product_code="SH", contract="SH2611"
        )
        self.assertEqual(2, len(rows))
        self.assertEqual(-4.29, rows[1]["basis_value"])
        self.assertEqual(1970.0, rows[1]["futures_price"])
        self.assertEqual(1965.71, rows[1]["spot_price"])


if __name__ == "__main__":
    unittest.main()
