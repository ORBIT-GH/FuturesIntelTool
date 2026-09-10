from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any, Mapping
from urllib.parse import urlparse
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

from .http import fetch_text


SHANGHAI = ZoneInfo("Asia/Shanghai")


def _strip_html(value: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", " ", value, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _first_text(node: ET.Element, names: tuple[str, ...]) -> str:
    for child in node.iter():
        if _local_name(child.tag) in names and child.text:
            return child.text.strip()
    return ""


def _first_link(node: ET.Element) -> str:
    for child in node.iter():
        if _local_name(child.tag) != "link":
            continue
        href = child.attrib.get("href")
        if href:
            return href.strip()
        if child.text:
            return child.text.strip()
    return ""


def _normalize_datetime(value: str) -> str | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=SHANGHAI)
        return parsed.isoformat(timespec="seconds")
    except (TypeError, ValueError, OverflowError):
        pass
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=SHANGHAI)
        return parsed.isoformat(timespec="seconds")
    except ValueError:
        return value


def _content_hash(title: str, summary: str, url: str) -> str:
    canonical = "\n".join(part.strip() for part in (title, summary, url))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _product_tags(text: str, keywords: Mapping[str, list[str]]) -> list[str]:
    lowered = text.lower()
    return [
        code.upper()
        for code, words in keywords.items()
        if any(str(word).lower() in lowered for word in words)
    ]


def parse_rss_feed(
    xml_text: str,
    *,
    feed_url: str = "",
    product_keywords: Mapping[str, list[str]] | None = None,
    fetched_at: str | None = None,
) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_text)
    entries = [node for node in root.iter() if _local_name(node.tag) in {"item", "entry"}]
    stamp = fetched_at or datetime.now(SHANGHAI).isoformat(timespec="seconds")
    host = urlparse(feed_url).netloc or "rss"
    keywords = product_keywords or {}
    rows: list[dict[str, Any]] = []
    for entry in entries:
        title = _strip_html(_first_text(entry, ("title",)))
        summary = _strip_html(
            _first_text(entry, ("description", "summary", "content", "encoded"))
        )
        url = _first_link(entry)
        published = _normalize_datetime(
            _first_text(entry, ("pubdate", "published", "updated", "date"))
        )
        if not title:
            continue
        products = _product_tags(f"{title} {summary}", keywords)
        rows.append(
            {
                "content_hash": _content_hash(title, summary, url),
                "published_at": published,
                "first_seen_at": stamp,
                "source": host,
                "title": title,
                "summary": summary,
                "url": url,
                "products_json": json.dumps(products, ensure_ascii=False),
                "tags_json": "[]",
                "raw_path": "",
            }
        )
    return rows


def fetch_rss_feed(
    url: str,
    *,
    product_keywords: Mapping[str, list[str]] | None = None,
    timeout: float = 20.0,
) -> list[dict[str, Any]]:
    xml_text = fetch_text(
        url,
        headers={"Accept": "application/rss+xml, application/atom+xml, text/xml"},
        timeout=timeout,
    )
    return parse_rss_feed(
        xml_text,
        feed_url=url,
        product_keywords=product_keywords,
    )
