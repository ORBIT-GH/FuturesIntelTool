from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence
from zoneinfo import ZoneInfo


SCHEMA_VERSION = "1"


def utc_now() -> str:
    return datetime.now(tz=ZoneInfo("UTC")).isoformat(timespec="seconds")


SCHEMA_SQL = r'''
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS collect_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trading_date TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('running', 'success', 'partial', 'failed')),
    message TEXT NOT NULL DEFAULT '',
    report_dir TEXT
);

CREATE TABLE IF NOT EXISTS source_health (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES collect_runs(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('success', 'partial', 'failed', 'skipped')),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    item_count INTEGER NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS contract_master (
    trading_date TEXT NOT NULL,
    product_code TEXT NOT NULL,
    contract TEXT NOT NULL,
    exchange TEXT NOT NULL DEFAULT '',
    open_interest REAL,
    volume REAL,
    rank INTEGER,
    is_main INTEGER NOT NULL DEFAULT 0 CHECK (is_main IN (0, 1)),
    rule_version TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (trading_date, contract)
);

CREATE INDEX IF NOT EXISTS idx_contract_master_product_date
    ON contract_master(product_code, trading_date, is_main);

CREATE TABLE IF NOT EXISTS futures_daily (
    trading_date TEXT NOT NULL,
    product_code TEXT NOT NULL,
    contract TEXT NOT NULL,
    exchange TEXT NOT NULL DEFAULT '',
    period TEXT NOT NULL DEFAULT '1d',
    session TEXT NOT NULL DEFAULT 'full' CHECK (session IN ('full', 'day', 'night')),
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    settlement REAL,
    previous_settlement REAL,
    volume REAL,
    open_interest REAL,
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (trading_date, contract, period, session)
);

CREATE INDEX IF NOT EXISTS idx_futures_daily_product_contract_date
    ON futures_daily(product_code, contract, trading_date);

CREATE TABLE IF NOT EXISTS positions (
    trading_date TEXT NOT NULL,
    product_code TEXT NOT NULL,
    contract TEXT NOT NULL,
    member TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('long', 'short', 'net_long', 'net_short')),
    rank INTEGER,
    position REAL NOT NULL,
    change REAL,
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (trading_date, contract, member, side, source)
);

CREATE INDEX IF NOT EXISTS idx_positions_product_date
    ON positions(product_code, trading_date, side, rank);

CREATE TABLE IF NOT EXISTS basis_history (
    quote_date TEXT NOT NULL,
    product_code TEXT NOT NULL,
    contract TEXT NOT NULL,
    definition_id TEXT NOT NULL,
    basis_value REAL,
    spot_price REAL,
    futures_price REAL,
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (quote_date, product_code, contract, definition_id, source)
);

CREATE TABLE IF NOT EXISTS spot_prices (
    quote_date TEXT NOT NULL,
    product_code TEXT NOT NULL,
    spec TEXT NOT NULL DEFAULT '',
    region TEXT NOT NULL DEFAULT '',
    quote_type TEXT NOT NULL DEFAULT '',
    price REAL,
    unit TEXT NOT NULL DEFAULT '元/吨',
    source TEXT NOT NULL,
    source_url TEXT NOT NULL DEFAULT '',
    raw_json TEXT NOT NULL DEFAULT '{}',
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (quote_date, product_code, spec, region, quote_type, source)
);

CREATE TABLE IF NOT EXISTS coal_prices (
    quote_date TEXT NOT NULL,
    benchmark TEXT NOT NULL,
    price REAL,
    change_pct REAL,
    unit TEXT NOT NULL DEFAULT '元/吨',
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (quote_date, benchmark, source)
);

CREATE TABLE IF NOT EXISTS news_items (
    content_hash TEXT PRIMARY KEY,
    published_at TEXT,
    first_seen_at TEXT NOT NULL,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    products_json TEXT NOT NULL DEFAULT '[]',
    tags_json TEXT NOT NULL DEFAULT '[]',
    raw_path TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_news_published_at ON news_items(published_at);

CREATE TABLE IF NOT EXISTS report_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trading_date TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    report_dir TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('success', 'partial', 'failed')),
    manifest_json TEXT NOT NULL,
    UNIQUE (trading_date, report_dir)
);
'''


class MarketDB:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connection() as conn:
            conn.executescript(SCHEMA_SQL)
            conn.execute(
                "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (SCHEMA_VERSION,),
            )

    def start_run(self, trading_date: str, started_at: str | None = None) -> int:
        stamp = started_at or utc_now()
        with self.connection() as conn:
            cur = conn.execute(
                "INSERT INTO collect_runs(trading_date, started_at, status) VALUES(?, ?, 'running')",
                (trading_date, stamp),
            )
            return int(cur.lastrowid)

    def finish_run(self, run_id: int, status: str, message: str = "", report_dir: str | None = None) -> None:
        if status not in {"success", "partial", "failed"}:
            raise ValueError(f"invalid run status: {status}")
        with self.connection() as conn:
            conn.execute(
                "UPDATE collect_runs SET finished_at=?, status=?, message=?, report_dir=? WHERE id=?",
                (utc_now(), status, message, report_dir, run_id),
            )

    def record_source_health(
        self,
        run_id: int,
        source: str,
        status: str,
        item_count: int = 0,
        message: str = "",
        started_at: str | None = None,
        finished_at: str | None = None,
    ) -> None:
        if status not in {"success", "partial", "failed", "skipped"}:
            raise ValueError(f"invalid source status: {status}")
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO source_health(
                    run_id, source, status, started_at, finished_at, item_count, message
                ) VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    source,
                    status,
                    started_at or utc_now(),
                    finished_at or utc_now(),
                    item_count,
                    message,
                ),
            )

    def upsert_contract_stats(self, rows: Iterable[Mapping[str, Any]]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        with self.connection() as conn:
            conn.executemany(
                """
                INSERT INTO contract_master(
                    trading_date, product_code, contract, exchange, open_interest,
                    volume, rank, is_main, rule_version, fetched_at
                ) VALUES(
                    :trading_date, :product_code, :contract, :exchange, :open_interest,
                    :volume, :rank, :is_main, :rule_version, :fetched_at
                )
                ON CONFLICT(trading_date, contract) DO UPDATE SET
                    product_code=excluded.product_code,
                    exchange=excluded.exchange,
                    open_interest=excluded.open_interest,
                    volume=excluded.volume,
                    rank=excluded.rank,
                    is_main=excluded.is_main,
                    rule_version=excluded.rule_version,
                    fetched_at=excluded.fetched_at
                """,
                rows,
            )
        return len(rows)

    def upsert_daily_bars(self, rows: Iterable[Mapping[str, Any]]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        normalized = []
        for row in rows:
            item = dict(row)
            item.setdefault("period", "1d")
            item.setdefault("session", "full")
            item.setdefault("exchange", "")
            normalized.append(item)
        with self.connection() as conn:
            conn.executemany(
                """
                INSERT INTO futures_daily(
                    trading_date, product_code, contract, exchange, period, session,
                    open, high, low, close, settlement, previous_settlement,
                    volume, open_interest, source, fetched_at
                ) VALUES(
                    :trading_date, :product_code, :contract, :exchange, :period, :session,
                    :open, :high, :low, :close, :settlement, :previous_settlement,
                    :volume, :open_interest, :source, :fetched_at
                )
                ON CONFLICT(trading_date, contract, period, session) DO UPDATE SET
                    product_code=excluded.product_code,
                    exchange=excluded.exchange,
                    open=excluded.open,
                    high=excluded.high,
                    low=excluded.low,
                    close=excluded.close,
                    settlement=excluded.settlement,
                    previous_settlement=excluded.previous_settlement,
                    volume=excluded.volume,
                    open_interest=excluded.open_interest,
                    source=excluded.source,
                    fetched_at=excluded.fetched_at
                """,
                normalized,
            )
        return len(normalized)

    def upsert_positions(self, rows: Iterable[Mapping[str, Any]]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        normalized = []
        for row in rows:
            item = dict(row)
            item.setdefault("rank", None)
            item.setdefault("change", None)
            normalized.append(item)
        with self.connection() as conn:
            conn.executemany(
                """
                INSERT INTO positions(
                    trading_date, product_code, contract, member, side, rank,
                    position, change, source, fetched_at
                ) VALUES(
                    :trading_date, :product_code, :contract, :member, :side, :rank,
                    :position, :change, :source, :fetched_at
                )
                ON CONFLICT(trading_date, contract, member, side, source) DO UPDATE SET
                    product_code=excluded.product_code,
                    rank=excluded.rank,
                    position=excluded.position,
                    change=excluded.change,
                    fetched_at=excluded.fetched_at
                """,
                normalized,
            )
        return len(normalized)

    def upsert_basis(self, rows: Iterable[Mapping[str, Any]]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        normalized = []
        for row in rows:
            item = dict(row)
            item.setdefault("basis_value", None)
            item.setdefault("spot_price", None)
            item.setdefault("futures_price", None)
            normalized.append(item)
        with self.connection() as conn:
            conn.executemany(
                """
                INSERT INTO basis_history(
                    quote_date, product_code, contract, definition_id,
                    basis_value, spot_price, futures_price, source, fetched_at
                ) VALUES(
                    :quote_date, :product_code, :contract, :definition_id,
                    :basis_value, :spot_price, :futures_price, :source, :fetched_at
                )
                ON CONFLICT(quote_date, product_code, contract, definition_id, source) DO UPDATE SET
                    basis_value=excluded.basis_value,
                    spot_price=excluded.spot_price,
                    futures_price=excluded.futures_price,
                    fetched_at=excluded.fetched_at
                """,
                normalized,
            )
        return len(normalized)

    def upsert_spot_prices(self, rows: Iterable[Mapping[str, Any]]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        normalized = []
        for row in rows:
            item = dict(row)
            item.setdefault("spec", "")
            item.setdefault("region", "")
            item.setdefault("quote_type", "")
            item.setdefault("price", None)
            item.setdefault("unit", "元/吨")
            item.setdefault("source_url", "")
            item.setdefault("raw_json", "{}")
            normalized.append(item)
        with self.connection() as conn:
            conn.executemany(
                """
                INSERT INTO spot_prices(
                    quote_date, product_code, spec, region, quote_type, price,
                    unit, source, source_url, raw_json, fetched_at
                ) VALUES(
                    :quote_date, :product_code, :spec, :region, :quote_type, :price,
                    :unit, :source, :source_url, :raw_json, :fetched_at
                )
                ON CONFLICT(quote_date, product_code, spec, region, quote_type, source)
                DO UPDATE SET
                    price=excluded.price,
                    unit=excluded.unit,
                    source_url=excluded.source_url,
                    raw_json=excluded.raw_json,
                    fetched_at=excluded.fetched_at
                """,
                normalized,
            )
        return len(normalized)

    def upsert_coal_prices(self, rows: Iterable[Mapping[str, Any]]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        normalized = []
        for row in rows:
            item = dict(row)
            item.setdefault("price", None)
            item.setdefault("change_pct", None)
            item.setdefault("unit", "元/吨")
            normalized.append(item)
        with self.connection() as conn:
            conn.executemany(
                """
                INSERT INTO coal_prices(
                    quote_date, benchmark, price, change_pct, unit, source, fetched_at
                ) VALUES(
                    :quote_date, :benchmark, :price, :change_pct, :unit, :source, :fetched_at
                )
                ON CONFLICT(quote_date, benchmark, source) DO UPDATE SET
                    price=excluded.price,
                    change_pct=excluded.change_pct,
                    unit=excluded.unit,
                    fetched_at=excluded.fetched_at
                """,
                normalized,
            )
        return len(normalized)

    def upsert_news(self, rows: Iterable[Mapping[str, Any]]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        normalized = []
        for row in rows:
            item = dict(row)
            item.setdefault("published_at", None)
            item.setdefault("summary", "")
            item.setdefault("url", "")
            item.setdefault("products_json", "[]")
            item.setdefault("tags_json", "[]")
            item.setdefault("raw_path", "")
            normalized.append(item)
        with self.connection() as conn:
            conn.executemany(
                """
                INSERT INTO news_items(
                    content_hash, published_at, first_seen_at, source, title,
                    summary, url, products_json, tags_json, raw_path
                ) VALUES(
                    :content_hash, :published_at, :first_seen_at, :source, :title,
                    :summary, :url, :products_json, :tags_json, :raw_path
                )
                ON CONFLICT(content_hash) DO UPDATE SET
                    published_at=COALESCE(excluded.published_at, news_items.published_at),
                    source=excluded.source,
                    title=excluded.title,
                    summary=CASE
                        WHEN length(excluded.summary) > length(news_items.summary)
                        THEN excluded.summary ELSE news_items.summary END,
                    url=CASE
                        WHEN excluded.url <> '' THEN excluded.url ELSE news_items.url END,
                    products_json=excluded.products_json,
                    tags_json=excluded.tags_json,
                    raw_path=CASE
                        WHEN excluded.raw_path <> '' THEN excluded.raw_path ELSE news_items.raw_path END
                """,
                normalized,
            )
        return len(normalized)

    def record_report_run(
        self,
        trading_date: str,
        report_dir: str,
        status: str,
        manifest_json: str,
        generated_at: str | None = None,
    ) -> None:
        if status not in {"success", "partial", "failed"}:
            raise ValueError(f"invalid report status: {status}")
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO report_runs(
                    trading_date, generated_at, report_dir, status, manifest_json
                ) VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(trading_date, report_dir) DO UPDATE SET
                    generated_at=excluded.generated_at,
                    status=excluded.status,
                    manifest_json=excluded.manifest_json
                """,
                (trading_date, generated_at or utc_now(), report_dir, status, manifest_json),
            )

    def scalar(self, sql: str, params: Sequence[Any] = ()) -> Any:
        with self.connection() as conn:
            row = conn.execute(sql, params).fetchone()
            return None if row is None else row[0]

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        with self.connection() as conn:
            return list(conn.execute(sql, params).fetchall())
