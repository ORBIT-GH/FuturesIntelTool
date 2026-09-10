from __future__ import annotations

import html
import re
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from .http import fetch_text


SHANGHAI = ZoneInfo("Asia/Shanghai")
SOURCE = "cctd"
BENCHMARKS = [
    "秦皇岛",
    "环渤海现货5500",
    "综合交易5500",
    "综合交易5000",
    "年度长协5500",
    "唐山主焦煤",
]


def _strip_html(source: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", " ", source, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "|", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return re.sub(r"\|+", "|", text)


def _infer_year(month_day: str, today: date) -> int:
    month, day = (int(part) for part in month_day.split("-"))
    candidate = date(today.year, month, day)
    if candidate > today:
        candidate = date(today.year - 1, month, day)
    return candidate.year


def parse_cctd_homepage(
    source: str,
    *,
    quote_date: str | None = None,
    fetched_at: str | None = None,
) -> list[dict[str, Any]]:
    text = _strip_html(source)
    now = datetime.now(SHANGHAI)
    fallback_day = quote_date or now.date().isoformat()
    stamp = fetched_at or now.isoformat(timespec="seconds")
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, float]] = set()
    for benchmark in BENCHMARKS:
        start = text.find(benchmark)
        if start < 0:
            continue
        segment = text[start + len(benchmark) : start + len(benchmark) + 260]
        price_match = re.search(
            r"(?<!\d)(\d{2,5}(?:\.\d+)?)\s*元\s*/\s*吨",
            segment,
        )
        if not price_match:
            price_match = re.search(r"(?<!\d)(\d{2,5}(?:\.\d+)?)(?!\d)", segment)
        if not price_match:
            continue
        price = float(price_match.group(1))
        key = (benchmark, price)
        if key in seen:
            continue
        seen.add(key)
        pct_match = re.search(r"([+-]?\d+(?:\.\d+)?)\s*%", segment)
        date_match = re.search(r"(?<!\d)(\d{2}-\d{2})(?!\d)", segment)
        date_hint = date_match.group(1) if date_match else None
        row_day = fallback_day
        if date_hint:
            row_day = f"{_infer_year(date_hint, now.date()):04d}-{date_hint}"
        rows.append(
            {
                "quote_date": row_day,
                "benchmark": benchmark,
                "price": price,
                "change_pct": float(pct_match.group(1)) if pct_match else None,
                "unit": "元/吨",
                "source": SOURCE,
                "fetched_at": stamp,
                "date_hint": date_hint,
            }
        )
    return rows


def fetch_coal_prices(*, timeout: float = 20.0) -> list[dict[str, Any]]:
    source = fetch_text(
        "https://www.cctd.com.cn/",
        encoding="gb18030",
        headers={"Accept": "text/html"},
        timeout=timeout,
    )
    return parse_cctd_homepage(source)

