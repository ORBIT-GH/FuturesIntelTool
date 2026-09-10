from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from futures_intel.db import MarketDB
from futures_intel.report import generate_daily_report


class ReportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = MarketDB(self.root / "market.sqlite")
        self.db.initialize()
        self.config = {
            "reports_dir": str(self.root / "reports"),
            "products": [{"code": "SH", "name": "烧碱", "exchange": "CZCE"}],
            "openclaw": {
                "default_files": ["manifest.json", "daily-brief.md", "anomalies.json"]
            },
        }
        self._seed()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _seed(self) -> None:
        stamp = "2026-09-10T18:05:00+08:00"
        self.db.upsert_contract_stats(
            [
                {
                    "trading_date": "2026-09-10",
                    "product_code": "SH",
                    "contract": "SH2611",
                    "exchange": "CZCE",
                    "open_interest": 234242,
                    "volume": 467719,
                    "rank": 1,
                    "is_main": 1,
                    "rule_version": "v1_oi_then_volume",
                    "fetched_at": stamp,
                }
            ]
        )
        self.db.upsert_daily_bars(
            [
                {
                    "trading_date": "2026-09-09",
                    "product_code": "SH",
                    "contract": "SH2611",
                    "open": 1968,
                    "high": 1995,
                    "low": 1952,
                    "close": 1970,
                    "settlement": 1973,
                    "previous_settlement": 1948,
                    "volume": 561340,
                    "open_interest": 236842,
                    "source": "sina",
                    "fetched_at": stamp,
                },
                {
                    "trading_date": "2026-09-10",
                    "product_code": "SH",
                    "contract": "SH2611",
                    "open": 1969,
                    "high": 2022,
                    "low": 1953,
                    "close": 2001,
                    "settlement": 2001,
                    "previous_settlement": 1973,
                    "volume": 467719,
                    "open_interest": 234242,
                    "source": "sina:quote",
                    "fetched_at": stamp,
                },
            ]
        )
        self.db.upsert_positions(
            [
                {
                    "trading_date": "2026-09-09",
                    "product_code": "SH",
                    "contract": "SH2611",
                    "member": "国泰君安",
                    "side": "long",
                    "rank": 1,
                    "position": 1000,
                    "change": 20,
                    "source": "jiaoyifamen",
                    "fetched_at": stamp,
                },
                {
                    "trading_date": "2026-09-09",
                    "product_code": "SH",
                    "contract": "SH2611",
                    "member": "中信期货",
                    "side": "short",
                    "rank": 1,
                    "position": 1200,
                    "change": -10,
                    "source": "jiaoyifamen",
                    "fetched_at": stamp,
                },
            ]
        )
        self.db.upsert_basis(
            [
                {
                    "quote_date": "2026-09-09",
                    "product_code": "SH",
                    "contract": "SH2611",
                    "definition_id": "jiaoyifamen_main_basis_v1",
                    "basis_value": -7.5,
                    "spot_price": 1962.5,
                    "futures_price": 1970,
                    "source": "jiaoyifamen",
                    "fetched_at": stamp,
                }
            ]
        )

    def test_generate_report_writes_openclaw_files(self) -> None:
        result = generate_daily_report(self.db, self.config, "2026-09-10")
        report_dir = Path(result["report_dir"])
        for name in (
            "daily-brief.md",
            "anomalies.json",
            "report.html",
            "manifest.json",
            "success.ok",
        ):
            self.assertTrue((report_dir / name).exists(), name)
        brief = (report_dir / "daily-brief.md").read_text(encoding="utf-8")
        self.assertIn("烧碱 SH2611", brief)
        self.assertIn("基差", brief)
        self.assertEqual("success", result["status"])
        self.assertTrue((Path(self.config["reports_dir"]) / "latest.json").exists())


if __name__ == "__main__":
    unittest.main()
