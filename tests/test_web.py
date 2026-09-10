from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from futures_intel.db import MarketDB
from futures_intel.report import generate_daily_report
from futures_intel.web import DashboardService, STATIC_DIR


class DashboardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = MarketDB(self.root / "market.sqlite")
        self.db.initialize()
        self.config = {
            "reports_dir": str(self.root / "reports"),
            "products": [{"code": "SH", "name": "烧碱", "exchange": "CZCE"}],
            "openclaw": {"default_files": ["manifest.json", "daily-brief.md", "anomalies.json"]},
        }
        stamp = "2026-09-10T18:05:00+08:00"
        self.db.upsert_contract_stats(
            [
                {
                    "trading_date": "2026-09-10",
                    "product_code": "SH",
                    "contract": "SH2611",
                    "exchange": "CZCE",
                    "open_interest": 100,
                    "volume": 200,
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
                    "trading_date": "2026-09-10",
                    "product_code": "SH",
                    "contract": "SH2611",
                    "open": 100,
                    "high": 110,
                    "low": 95,
                    "close": 105,
                    "settlement": 104,
                    "previous_settlement": 100,
                    "volume": 200,
                    "open_interest": 100,
                    "source": "test",
                    "fetched_at": stamp,
                }
            ]
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_dashboard_summary_and_report(self) -> None:
        service = DashboardService(self.config, self.db)
        summary = service.summary("2026-09-10")
        self.assertEqual("SH2611", summary["context"]["products"][0]["contract"])
        self.assertFalse(service.report("2026-09-10")["available"])

        generate_daily_report(self.db, self.config, "2026-09-10")
        report = service.report("2026-09-10")
        self.assertTrue(report["available"])
        self.assertIn("烧碱", report["brief"])

    def test_static_dashboard_files_exist(self) -> None:
        for name in ("index.html", "app.js", "styles.css"):
            self.assertTrue((STATIC_DIR / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
