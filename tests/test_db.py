from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from futures_intel.db import MarketDB


class MarketDBTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db = MarketDB(Path(self.temp.name) / "market.sqlite")
        self.db.initialize()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_contract_stats_are_idempotent(self) -> None:
        row = {
            "trading_date": "2026-09-10",
            "product_code": "SH",
            "contract": "SH2611",
            "exchange": "CZCE",
            "open_interest": 234242,
            "volume": 467719,
            "rank": 1,
            "is_main": 1,
            "rule_version": "v1_oi_then_volume",
            "fetched_at": "2026-09-10T18:05:00+08:00",
        }
        self.db.upsert_contract_stats([row])
        row["open_interest"] = 235000
        self.db.upsert_contract_stats([row])

        rows = self.db.query("SELECT * FROM contract_master")
        self.assertEqual(1, len(rows))
        self.assertEqual(235000, rows[0]["open_interest"])

    def test_daily_bar_upsert_keeps_one_record_per_day_and_session(self) -> None:
        row = {
            "trading_date": "2026-09-10",
            "product_code": "SH",
            "contract": "SH2611",
            "open": 1969,
            "high": 2022,
            "low": 1953,
            "close": 2001,
            "settlement": 1973,
            "previous_settlement": 1944,
            "volume": 467719,
            "open_interest": 234242,
            "source": "sina",
            "fetched_at": "2026-09-10T18:05:00+08:00",
        }
        self.db.upsert_daily_bars([row])
        row["close"] = 2002
        self.db.upsert_daily_bars([row])

        rows = self.db.query("SELECT * FROM futures_daily")
        self.assertEqual(1, len(rows))
        self.assertEqual(2002, rows[0]["close"])

    def test_news_content_hash_deduplicates(self) -> None:
        row = {
            "content_hash": "abc123",
            "published_at": "2026-09-10T08:00:00+08:00",
            "first_seen_at": "2026-09-10T08:01:00+08:00",
            "source": "test",
            "title": "示例新闻",
            "summary": "短摘要",
            "url": "https://example.com/a",
            "products_json": "[\"SH\"]",
            "tags_json": "[]",
            "raw_path": "",
        }
        self.db.upsert_news([row])
        row["summary"] = "这是一条更完整的摘要"
        self.db.upsert_news([row])

        rows = self.db.query("SELECT * FROM news_items")
        self.assertEqual(1, len(rows))
        self.assertEqual("这是一条更完整的摘要", rows[0]["summary"])

    def test_run_lifecycle(self) -> None:
        run_id = self.db.start_run("2026-09-10", "2026-09-10T18:05:00+08:00")
        self.db.record_source_health(run_id, "sina", "success", 10)
        self.db.finish_run(run_id, "success", "ok")

        runs = self.db.query("SELECT * FROM collect_runs")
        health = self.db.query("SELECT * FROM source_health")
        self.assertEqual("success", runs[0]["status"])
        self.assertEqual(10, health[0]["item_count"])


if __name__ == "__main__":
    unittest.main()
