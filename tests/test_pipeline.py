from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from futures_intel.db import MarketDB
from futures_intel.pipeline import Collector


CONFIG = {
    "products": [
        {"code": "SH", "name": "烧碱", "exchange": "CZCE"},
    ],
    "contract_months_ahead": 2,
    "history_days": 120,
}


QUOTES = [
    {
        "trading_date": "2026-09-10",
        "product_code": "SH",
        "contract": "SH2611",
        "name": "烧碱2611",
        "open": 1969.0,
        "high": 2022.0,
        "low": 1953.0,
        "last": 2001.0,
        "settlement": 1973.0,
        "previous_settlement": 1944.0,
        "volume": 467719.0,
        "open_interest": 234242.0,
        "source": "sina",
        "fetched_at": "2026-09-10T18:05:00+08:00",
    }
]

POSITION = {
    "code": 200,
    "data": {
        "futureName": "烧碱611",
        "instrument": "SH611",
        "long_rank_table": [
            {"day": "2026-09-09 00:00:00", "rank": 1, "memberName": "A", "indicator": 10, "indicatorIncrease": 1}
        ],
        "short_rank_table": [
            {"day": "2026-09-09 00:00:00", "rank": 1, "memberName": "B", "indicator": 12, "indicatorIncrease": -1}
        ],
    },
}

BASIS = {
    "code": 200,
    "data": {
        "category": ["2026-09-09"],
        "basisValue": [-7.5],
        "priceValue": [1970.0],
    },
}


def daily_fetcher(contract: str, *, product_code: str):
    return [
        {
            "trading_date": "2026-09-09",
            "product_code": product_code,
            "contract": contract,
            "period": "1d",
            "session": "full",
            "open": 1968.0,
            "high": 1995.0,
            "low": 1952.0,
            "close": 1970.0,
            "settlement": 1973.0,
            "previous_settlement": 1948.0,
            "volume": 561340.0,
            "open_interest": 236842.0,
            "source": "sina",
            "fetched_at": "2026-09-10T18:05:00+08:00",
        }
    ]


class PipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db = MarketDB(Path(self.temp.name) / "market.sqlite")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_collector_writes_all_sources(self) -> None:
        collector = Collector(
            CONFIG,
            self.db,
            fetchers={
                "quotes": lambda contracts: QUOTES,
                "daily": daily_fetcher,
                "position": lambda code: POSITION,
                "basis": lambda code: BASIS,
                "coal": lambda: [],
            },
        )
        result = collector.collect("2026-09-10")
        self.assertEqual("success", result.status)
        self.assertEqual(1, self.db.scalar("SELECT COUNT(*) FROM contract_master"))
        self.assertEqual(2, self.db.scalar("SELECT COUNT(*) FROM futures_daily"))
        self.assertEqual(2, self.db.scalar("SELECT COUNT(*) FROM positions"))
        self.assertEqual(1, self.db.scalar("SELECT COUNT(*) FROM basis_history"))
        self.assertIn("煤价数据暂缺", result.warnings)

    def test_collector_marks_partial_when_position_fails(self) -> None:
        def fail(code: str):
            raise RuntimeError("network down")

        collector = Collector(
            CONFIG,
            self.db,
            fetchers={
                "quotes": lambda contracts: QUOTES,
                "daily": daily_fetcher,
                "position": fail,
                "basis": lambda code: BASIS,
                "coal": lambda: [],
            },
        )
        result = collector.collect("2026-09-10")
        self.assertEqual("partial", result.status)
        self.assertTrue(any("持仓失败" in item for item in result.errors))


    def test_contract_override_beats_auto_main(self) -> None:
        config = dict(CONFIG)
        config["products"] = [
            {
                "code": "SH",
                "name": "烧碱",
                "exchange": "CZCE",
                "contract_override": "SH2701",
            }
        ]
        quotes = QUOTES + [
            {
                **QUOTES[0],
                "contract": "SH2701",
                "name": "烧碱2701",
                "open_interest": 71827.0,
                "volume": 59410.0,
            }
        ]
        calls: list[str] = []

        def daily(contract: str, *, product_code: str):
            calls.append(contract)
            return daily_fetcher(contract, product_code=product_code)

        collector = Collector(
            config,
            self.db,
            fetchers={
                "quotes": lambda contracts: quotes,
                "daily": daily,
                "position": lambda code: POSITION,
                "basis": lambda code: BASIS,
                "coal": lambda: [],
            },
        )
        result = collector.collect("2026-09-10")
        self.assertEqual("success", result.status)
        main = self.db.query("SELECT * FROM contract_master WHERE is_main=1")
        self.assertEqual("SH2701", main[0]["contract"])
        self.assertEqual("config_override", main[0]["rule_version"])
        self.assertEqual(["SH2701"], calls)


if __name__ == "__main__":
    unittest.main()
