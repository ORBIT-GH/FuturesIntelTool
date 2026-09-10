from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Sequence

from .calendar import is_trading_day
from .config import ensure_runtime_dirs, load_config
from .db import MarketDB
from .imports import import_news_records, import_spot_records
from .pipeline import Collector
from .report import generate_daily_report


def _json_default(value: Any) -> str:
    return str(value)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="futures-intel",
        description="本地期货资讯采集、简报和 OpenClaw 文件接口",
    )
    parser.add_argument("--config", default=None, help="配置文件路径")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="初始化数据库和目录")

    collect = sub.add_parser("collect", help="采集行情、持仓、基差和煤价")
    collect.add_argument("--date", help="交易日，默认今天")

    report = sub.add_parser("report", help="生成日报和 OpenClaw 文件")
    report.add_argument("--date", help="交易日，默认今天")

    scheduled = sub.add_parser("scheduled-run", help="交易日定时采集并生成日报")
    scheduled.add_argument("--date", help="交易日，默认今天")

    run = sub.add_parser("run", help="采集后生成日报")
    run.add_argument("--date", help="交易日，默认今天")

    import_news = sub.add_parser("import-news", help="导入新闻 JSON/JSONL/CSV")
    import_news.add_argument("--file", required=True)
    import_news.add_argument("--source", default="manual")

    import_spot = sub.add_parser("import-spot", help="导入现货价 JSON/JSONL/CSV")
    import_spot.add_argument("--file", required=True)
    import_spot.add_argument("--product", required=True)
    import_spot.add_argument("--spec", default="")
    import_spot.add_argument("--region", default="")
    import_spot.add_argument("--quote-type", default="")
    import_spot.add_argument("--source", default="manual")

    query = sub.add_parser("query", help="查询本地数据")
    query.add_argument("kind", choices=["market", "news", "runs", "health"])
    query.add_argument("--date")
    query.add_argument("--product")
    query.add_argument("--limit", type=int, default=20)

    return parser


def _print(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))


def _query(db: MarketDB, args: argparse.Namespace) -> Any:
    if args.kind == "market":
        clauses = ["1=1"]
        params: list[Any] = []
        if args.date:
            clauses.append("trading_date <= ?")
            params.append(args.date)
        if args.product:
            clauses.append("product_code = ?")
            params.append(args.product.upper())
        params.append(max(1, args.limit))
        sql = f"""
            SELECT trading_date, product_code, contract, exchange, open_interest,
                   volume, rank, is_main, rule_version, fetched_at
            FROM contract_master
            WHERE {' AND '.join(clauses)}
            ORDER BY trading_date DESC, product_code, rank
            LIMIT ?
        """
        return [dict(row) for row in db.query(sql, params)]

    if args.kind == "news":
        clauses = ["1=1"]
        params: list[Any] = []
        if args.date:
            clauses.append("substr(COALESCE(published_at, first_seen_at), 1, 10) <= ?")
            params.append(args.date)
        if args.product:
            clauses.append("products_json LIKE ?")
            params.append(f'%"{args.product.upper()}"%')
        params.append(max(1, args.limit))
        sql = f"""
            SELECT content_hash, published_at, source, title, summary, url,
                   products_json, tags_json
            FROM news_items
            WHERE {' AND '.join(clauses)}
            ORDER BY COALESCE(published_at, first_seen_at) DESC
            LIMIT ?
        """
        return [dict(row) for row in db.query(sql, params)]

    if args.kind == "runs":
        return [
            dict(row)
            for row in db.query(
                "SELECT * FROM collect_runs ORDER BY id DESC LIMIT ?",
                (max(1, args.limit),),
            )
        ]

    return [
        dict(row)
        for row in db.query(
            "SELECT * FROM source_health ORDER BY id DESC LIMIT ?",
            (max(1, args.limit),),
        )
    ]


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        ensure_runtime_dirs(config)
        db = MarketDB(config["database"])
    except Exception as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        return 2

    if args.command == "init":
        db.initialize()
        _print(
            {
                "status": "ok",
                "database": config["database"],
                "reports_dir": config["reports_dir"],
            }
        )
        return 0

    if args.command == "collect":
        result = Collector(config, db).collect(args.date)
        _print(result.as_dict())
        return 0 if result.status in {"success", "partial"} else 1

    if args.command == "report":
        result = generate_daily_report(db, config, args.date)
        _print(result)
        return 0 if result["status"] in {"success", "partial"} else 1

    if args.command == "scheduled-run":
        if not is_trading_day(args.date, config):
            _print({"status": "skipped", "reason": "not_trading_day", "date": args.date})
            return 0
        collect_result = Collector(config, db).collect(args.date)
        report_result = generate_daily_report(db, config, args.date)
        _print({"collect": collect_result.as_dict(), "report": report_result})
        return 0 if report_result["status"] in {"success", "partial"} else 1

    if args.command == "run":
        collect_result = Collector(config, db).collect(args.date)
        report_result = generate_daily_report(db, config, args.date)
        _print({"collect": collect_result.as_dict(), "report": report_result})
        return 0 if report_result["status"] in {"success", "partial"} else 1

    if args.command == "import-news":
        db.initialize()
        count = import_news_records(db, args.file, source=args.source)
        _print({"status": "ok", "imported": count})
        return 0

    if args.command == "import-spot":
        db.initialize()
        count = import_spot_records(
            db,
            args.file,
            product_code=args.product,
            spec=args.spec,
            region=args.region,
            quote_type=args.quote_type,
            source=args.source,
        )
        _print({"status": "ok", "imported": count})
        return 0

    if args.command == "query":
        db.initialize()
        _print(_query(db, args))
        return 0

    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
