from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

from .db import MarketDB, utc_now
from .sources import (
    candidate_contracts,
    choose_main_contract,
    fetch_basis,
    fetch_coal_prices,
    fetch_daily_kline,
    fetch_position,
    fetch_quotes,
    parse_basis_payload,
    parse_position_payload,
    fetch_rss_feed,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(slots=True)
class CollectResult:
    run_id: int
    trading_date: str
    status: str
    item_count: int
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "trading_date": self.trading_date,
            "status": self.status,
            "item_count": self.item_count,
            "errors": self.errors,
            "warnings": self.warnings,
        }


class Collector:
    def __init__(
        self,
        config: Mapping[str, Any],
        db: MarketDB,
        *,
        fetchers: Mapping[str, Callable[..., Any]] | None = None,
    ):
        self.config = dict(config)
        self.db = db
        self.fetchers: dict[str, Callable[..., Any]] = {
            "quotes": fetch_quotes,
            "daily": fetch_daily_kline,
            "position": fetch_position,
            "basis": fetch_basis,
            "coal": fetch_coal_prices,
            "rss": fetch_rss_feed,
        }
        if fetchers:
            self.fetchers.update(fetchers)

    def collect(self, trading_date: str | None = None) -> CollectResult:
        self.db.initialize()
        now = datetime.now(SHANGHAI)
        requested_date = trading_date or now.date().isoformat()
        run_id = self.db.start_run(requested_date, now.isoformat(timespec="seconds"))
        errors: list[str] = []
        warnings: list[str] = []
        item_count = 0
        successful_products = 0

        products = list(self.config["products"])
        all_contracts: list[str] = []
        for product in products:
            all_contracts.extend(
                candidate_contracts(
                    product["code"],
                    requested_date,
                    int(self.config.get("contract_months_ahead", 20)),
                )
            )

        quote_started = utc_now()
        selected_main: dict[str, dict[str, Any]] = {}
        try:
            quotes = self.fetchers["quotes"](all_contracts)
            quote_rows: list[dict[str, Any]] = []
            for product in products:
                code = product["code"]
                ranked = choose_main_contract(quotes, code)
                override = str(product.get("contract_override") or "").strip().upper()
                selected: dict[str, Any] | None = None
                if override:
                    existing = next(
                        (row for row in ranked if row["contract"] == override),
                        None,
                    )
                    selected = dict(existing) if existing else {
                        "trading_date": requested_date,
                        "product_code": code,
                        "contract": override,
                        "open_interest": None,
                        "volume": None,
                        "source": "config",
                        "fetched_at": now.isoformat(timespec="seconds"),
                    }
                    selected.update(
                        {
                            "rank": 1,
                            "is_main": 1,
                            "rule_version": "config_override",
                        }
                    )
                    ranked = [selected] + [
                        row for row in ranked if row["contract"] != override
                    ]
                    for index, row in enumerate(ranked, start=1):
                        row["rank"] = index
                        row["is_main"] = 1 if index == 1 else 0
                elif ranked:
                    selected = ranked[0]
                if selected:
                    selected_main[code] = selected
                for row in ranked:
                    row["exchange"] = product.get("exchange", "")
                quote_rows.extend(ranked)
            count = self.db.upsert_contract_stats(quote_rows)
            item_count += count
            if not quote_rows:
                raise ValueError("no valid contract quotes returned")
            self.db.record_source_health(
                run_id,
                "sina:quotes",
                "success",
                count,
                started_at=quote_started,
            )
        except Exception as exc:
            errors.append(f"Sina行情失败: {exc}")
            self.db.record_source_health(
                run_id,
                "sina:quotes",
                "failed",
                message=str(exc),
                started_at=quote_started,
            )
            quotes = []
            selected_main = {}

        for product in products:
            code = product["code"]
            exchange = product.get("exchange", "")
            main = selected_main.get(code)
            if main is None:
                errors.append(f"{code} 无法判定主力合约")
                continue
            contract = main["contract"]

            kline_started = utc_now()
            try:
                bars = self.fetchers["daily"](contract, product_code=code)
                bars = [bar for bar in bars if bar["trading_date"] <= requested_date]
                bars_by_date = {bar["trading_date"]: bar for bar in bars}
                quote_date = str(main.get("trading_date") or "")[:10]
                if quote_date and quote_date <= requested_date:
                    quote_close = main.get("last") or main.get("settlement")
                    bars_by_date[quote_date] = {
                        "trading_date": quote_date,
                        "product_code": code,
                        "contract": contract,
                        "period": "1d",
                        "session": "full",
                        "open": main.get("open"),
                        "high": main.get("high"),
                        "low": main.get("low"),
                        "close": quote_close,
                        "settlement": main.get("settlement") or quote_close,
                        "previous_settlement": main.get("previous_settlement"),
                        "volume": main.get("volume"),
                        "open_interest": main.get("open_interest"),
                        "source": "sina:quote",
                        "fetched_at": main.get("fetched_at") or now.isoformat(timespec="seconds"),
                    }
                bars = sorted(bars_by_date.values(), key=lambda bar: bar["trading_date"])
                history_days = max(60, int(self.config.get("history_days", 180)))
                bars = bars[-history_days:]
                for bar in bars:
                    bar["exchange"] = exchange
                count = self.db.upsert_daily_bars(bars)
                item_count += count
                self.db.record_source_health(
                    run_id,
                    f"sina:kline:{code}",
                    "success" if bars else "partial",
                    count,
                    "未返回日K数据" if not bars else "",
                    started_at=kline_started,
                )
                if bars:
                    successful_products += 1
                else:
                    errors.append(f"{code} 日K数据为空")
            except Exception as exc:
                errors.append(f"{code} 日K失败: {exc}")
                self.db.record_source_health(
                    run_id,
                    f"sina:kline:{code}",
                    "failed",
                    message=str(exc),
                    started_at=kline_started,
                )
            time.sleep(0.08)

            position_started = utc_now()
            try:
                position_payload = self.fetchers["position"](code)
                position = parse_position_payload(
                    position_payload,
                    product_code=code,
                    fetched_at=now.isoformat(timespec="seconds"),
                )
                count = self.db.upsert_positions(position["positions"])
                item_count += count
                self.db.record_source_health(
                    run_id,
                    f"jiaoyifamen:position:{code}",
                    "success",
                    count,
                    started_at=position_started,
                )
            except Exception as exc:
                errors.append(f"{code} 持仓失败: {exc}")
                self.db.record_source_health(
                    run_id,
                    f"jiaoyifamen:position:{code}",
                    "failed",
                    message=str(exc),
                    started_at=position_started,
                )
                position = None

            basis_started = utc_now()
            try:
                basis_payload = self.fetchers["basis"](code)
                if position is None:
                    raise ValueError("持仓数据不可用，无法确定基差合约")
                basis_rows = parse_basis_payload(
                    basis_payload,
                    product_code=code,
                    contract=position["contract"],
                    fetched_at=now.isoformat(timespec="seconds"),
                )
                count = self.db.upsert_basis(basis_rows)
                item_count += count
                self.db.record_source_health(
                    run_id,
                    f"jiaoyifamen:basis:{code}",
                    "success" if basis_rows else "partial",
                    count,
                    "未返回基差数据" if not basis_rows else "",
                    started_at=basis_started,
                )
                if not basis_rows:
                    warnings.append(f"{code} 基差数据为空")
            except Exception as exc:
                errors.append(f"{code} 基差失败: {exc}")
                self.db.record_source_health(
                    run_id,
                    f"jiaoyifamen:basis:{code}",
                    "failed",
                    message=str(exc),
                    started_at=basis_started,
                )
            time.sleep(0.08)

        coal_started = utc_now()
        try:
            coal_rows = self.fetchers["coal"]()
            count = self.db.upsert_coal_prices(coal_rows)
            item_count += count
            self.db.record_source_health(
                run_id,
                "cctd:coal",
                "success" if coal_rows else "skipped",
                count,
                "" if coal_rows else "首页未解析到煤价指标",
                started_at=coal_started,
            )
            if not coal_rows:
                warnings.append("煤价数据暂缺")
        except Exception as exc:
            warnings.append(f"煤价数据暂缺: {exc}")
            self.db.record_source_health(
                run_id,
                "cctd:coal",
                "skipped",
                message=str(exc),
                started_at=coal_started,
            )

        for feed in self.config.get("rss_feeds", []):
            feed_url = str(feed.get("url") if isinstance(feed, Mapping) else feed)
            if not feed_url:
                continue
            rss_started = utc_now()
            try:
                news_rows = self.fetchers["rss"](
                    feed_url,
                    product_keywords=self.config.get("news_keywords", {}),
                )
                count = self.db.upsert_news(news_rows)
                item_count += count
                self.db.record_source_health(
                    run_id,
                    f"rss:{feed_url}",
                    "success" if news_rows else "partial",
                    count,
                    "未返回新闻" if not news_rows else "",
                    started_at=rss_started,
                )
            except Exception as exc:
                warnings.append(f"新闻源暂缺 {feed_url}: {exc}")
                self.db.record_source_health(
                    run_id,
                    f"rss:{feed_url}",
                    "failed",
                    message=str(exc),
                    started_at=rss_started,
                )

        if successful_products == 0:
            status = "failed"
        elif errors:
            status = "partial"
        else:
            status = "success"
        message_parts = []
        if errors:
            message_parts.append("; ".join(errors[:8]))
        if warnings:
            message_parts.append("; ".join(warnings[:8]))
        self.db.finish_run(run_id, status, " | ".join(message_parts))
        return CollectResult(
            run_id=run_id,
            trading_date=requested_date,
            status=status,
            item_count=item_count,
            errors=errors,
            warnings=warnings,
        )
