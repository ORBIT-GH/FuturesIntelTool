from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .db import MarketDB


SHANGHAI = ZoneInfo("Asia/Shanghai")


def _load_records(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix == ".jsonl":
        return [
            json.loads(line)
            for line in source.read_text(encoding="utf-8-sig").splitlines()
            if line.strip()
        ]
    if suffix == ".json":
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
        if isinstance(payload, list):
            return [dict(item) for item in payload]
        if isinstance(payload, dict) and isinstance(payload.get("items"), list):
            return [dict(item) for item in payload["items"]]
        if isinstance(payload, dict):
            return [payload]
        raise ValueError("JSON import must be an object or list")
    if suffix in {".csv", ".tsv"}:
        delimiter = "\t" if suffix == ".tsv" else ","
        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle, delimiter=delimiter)]
    raise ValueError(f"unsupported import format: {source.suffix}")


def _split_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in str(value).replace("|", ",").split(",") if part.strip()]


def import_news_records(
    db: MarketDB,
    path: str | Path,
    *,
    source: str = "manual",
) -> int:
    stamp = datetime.now(SHANGHAI).isoformat(timespec="seconds")
    rows: list[dict[str, Any]] = []
    for record in _load_records(path):
        title = str(record.get("title") or "").strip()
        if not title:
            continue
        summary = str(record.get("summary") or record.get("content") or "").strip()
        url = str(record.get("url") or record.get("link") or "").strip()
        content_hash = str(record.get("content_hash") or "").strip()
        if not content_hash:
            content_hash = hashlib.sha256(
                f"{title}\n{summary}\n{url}".encode("utf-8")
            ).hexdigest()
        products = _split_list(record.get("products") or record.get("product_codes"))
        tags = _split_list(record.get("tags"))
        rows.append(
            {
                "content_hash": content_hash,
                "published_at": record.get("published_at") or record.get("date"),
                "first_seen_at": record.get("first_seen_at") or stamp,
                "source": record.get("source") or source,
                "title": title,
                "summary": summary,
                "url": url,
                "products_json": json.dumps(products, ensure_ascii=False),
                "tags_json": json.dumps(tags, ensure_ascii=False),
                "raw_path": str(Path(path).resolve()),
            }
        )
    deduped = {row["content_hash"]: row for row in rows}
    return db.upsert_news(deduped.values())


def import_spot_records(
    db: MarketDB,
    path: str | Path,
    *,
    product_code: str,
    spec: str = "",
    region: str = "",
    quote_type: str = "",
    source: str = "manual",
) -> int:
    stamp = datetime.now(SHANGHAI).isoformat(timespec="seconds")
    rows: list[dict[str, Any]] = []
    for record in _load_records(path):
        quote_date = str(record.get("quote_date") or record.get("date") or "").strip()
        if not quote_date or record.get("price") in (None, ""):
            continue
        rows.append(
            {
                "quote_date": quote_date[:10],
                "product_code": str(record.get("product_code") or product_code).upper(),
                "spec": str(record.get("spec") or spec),
                "region": str(record.get("region") or region),
                "quote_type": str(record.get("quote_type") or quote_type),
                "price": float(record["price"]),
                "unit": str(record.get("unit") or "元/吨"),
                "source": str(record.get("source") or source),
                "source_url": str(record.get("source_url") or ""),
                "raw_json": json.dumps(record, ensure_ascii=False),
                "fetched_at": record.get("fetched_at") or stamp,
            }
        )
    return db.upsert_spot_prices(rows)

