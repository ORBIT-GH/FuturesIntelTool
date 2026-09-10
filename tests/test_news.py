from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from futures_intel.db import MarketDB
from futures_intel.imports import import_news_records, import_spot_records
from futures_intel.sources.rss import parse_rss_feed


RSS = '''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><item>
<title>山东烧碱现货报价上调</title>
<link>https://example.com/news/1</link>
<description><![CDATA[液碱市场小幅走强，关注氯碱开工。]]></description>
<pubDate>Wed, 09 Sep 2026 10:00:00 +0800</pubDate>
</item></channel></rss>'''


class NewsImportTest(unittest.TestCase):
    def test_parse_rss_and_tag_product(self) -> None:
        rows = parse_rss_feed(
            RSS,
            feed_url="https://example.com/rss",
            product_keywords={"SH": ["烧碱", "液碱", "氯碱"]},
            fetched_at="2026-09-10T18:05:00+08:00",
        )
        self.assertEqual(1, len(rows))
        self.assertEqual(["SH"], json.loads(rows[0]["products_json"]))
        self.assertEqual("example.com", rows[0]["source"])

    def test_import_news_and_spot_with_hash_dedupe(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db = MarketDB(root / "market.sqlite")
            db.initialize()
            news_file = root / "news.json"
            news_file.write_text(
                json.dumps(
                    [
                        {
                            "title": "烧碱新闻",
                            "summary": "摘要",
                            "url": "https://example.com/a",
                            "published_at": "2026-09-10T08:00:00+08:00",
                            "products": ["SH"],
                        },
                        {
                            "title": "烧碱新闻",
                            "summary": "摘要",
                            "url": "https://example.com/a",
                        },
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            count = import_news_records(db, news_file)
            self.assertEqual(1, db.scalar("SELECT COUNT(*) FROM news_items"))
            self.assertEqual(1, count)

            spot_file = root / "spot.csv"
            spot_file.write_text(
                "quote_date,price\n2026-09-09,625\n2026-09-10,628\n",
                encoding="utf-8",
            )
            imported = import_spot_records(
                db,
                spot_file,
                product_code="SH",
                spec="32%液碱",
                region="山东",
                source="taoge",
            )
            self.assertEqual(2, imported)
            self.assertEqual(2, db.scalar("SELECT COUNT(*) FROM spot_prices"))


if __name__ == "__main__":
    unittest.main()
