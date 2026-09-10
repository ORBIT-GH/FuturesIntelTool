from __future__ import annotations

import hashlib
import html
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping
from uuid import uuid4
from zoneinfo import ZoneInfo

from .db import MarketDB


SHANGHAI = ZoneInfo("Asia/Shanghai")


def _number(value: Any, digits: int = 2) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _fmt(value: Any, digits: int = 2, empty: str = "-") -> str:
    number = _number(value, digits)
    if number is None:
        return empty
    if number == int(number):
        return f"{int(number):,}"
    return f"{number:,.{digits}f}".rstrip("0").rstrip(".")


def _pct(value: Any, digits: int = 2) -> str:
    number = _number(value, digits)
    if number is None:
        return "-"
    return f"{number:+.{digits}f}%"


def _change_info(latest: Mapping[str, Any], previous: Mapping[str, Any] | None) -> dict[str, Any]:
    close = _number(latest.get("close"))
    baseline = None
    if previous is not None:
        baseline = _number(previous.get("settlement")) or _number(previous.get("close"))
    if baseline in (None, 0) or close is None:
        return {"change": None, "change_pct": None}
    change = close - baseline
    return {"change": change, "change_pct": change / baseline * 100}


def _average(values: Iterable[Any], window: int) -> float | None:
    clean = [_number(value) for value in values]
    selected = [value for value in clean if value is not None][:window]
    if not selected:
        return None
    return sum(selected) / len(selected)


def _latest_table_date(db: MarketDB, table: str, date_column: str, date: str) -> str | None:
    value = db.scalar(
        f"SELECT MAX({date_column}) FROM {table} WHERE {date_column} <= ?",
        (date,),
    )
    return str(value) if value else None


def build_report_context(
    db: MarketDB,
    config: Mapping[str, Any],
    trading_date: str | None = None,
) -> dict[str, Any]:
    requested_date = trading_date or datetime.now(SHANGHAI).date().isoformat()
    latest_market_date = db.scalar(
        "SELECT MAX(trading_date) FROM futures_daily WHERE trading_date <= ?",
        (requested_date,),
    )
    effective_market_date = str(latest_market_date or requested_date)
    anomalies: list[dict[str, Any]] = []
    products: list[dict[str, Any]] = []

    for product_config in config["products"]:
        code = str(product_config["code"]).upper()
        name = str(product_config["name"])
        row = db.query(
            """
            SELECT * FROM contract_master
            WHERE product_code=? AND is_main=1 AND trading_date<=?
            ORDER BY trading_date DESC LIMIT 1
            """,
            (code, requested_date),
        )
        if not row:
            products.append({"code": code, "name": name, "missing": True})
            anomalies.append(
                {
                    "severity": "error",
                    "code": "missing_main_contract",
                    "product": code,
                    "message": f"{name} 未找到主力合约数据",
                }
            )
            continue

        main = dict(row[0])
        contract = str(main["contract"])
        bars_desc = db.query(
            """
            SELECT * FROM futures_daily
            WHERE product_code=? AND contract=? AND period='1d' AND session='full'
              AND trading_date<=?
            ORDER BY trading_date DESC LIMIT 61
            """,
            (code, contract, requested_date),
        )
        if not bars_desc:
            products.append(
                {
                    "code": code,
                    "name": name,
                    "missing": True,
                    "contract": contract,
                    "main": main,
                }
            )
            anomalies.append(
                {
                    "severity": "error",
                    "code": "missing_daily_bar",
                    "product": code,
                    "message": f"{name} {contract} 未找到日K数据",
                }
            )
            continue

        latest_bar = dict(bars_desc[0])
        previous_bar = dict(bars_desc[1]) if len(bars_desc) > 1 else None
        movement = _change_info(latest_bar, previous_bar)
        closes = [bar["close"] for bar in bars_desc]
        item: dict[str, Any] = {
            "code": code,
            "name": name,
            "missing": False,
            "main": main,
            "contract": contract,
            "bar": latest_bar,
            "previous_bar": previous_bar,
            "change": movement["change"],
            "change_pct": movement["change_pct"],
            "ma5": _average(closes, 5),
            "ma10": _average(closes, 10),
            "ma20": _average(closes, 20),
            "ma60": _average(closes, 60),
            "volume_change": None,
            "oi_change": None,
        }
        if previous_bar is not None:
            if _number(previous_bar.get("volume")) not in (None, 0) and latest_bar.get("volume") is not None:
                item["volume_change"] = (
                    float(latest_bar["volume"]) / float(previous_bar["volume"]) - 1
                ) * 100
            if latest_bar.get("open_interest") is not None and previous_bar.get("open_interest") is not None:
                item["oi_change"] = float(latest_bar["open_interest"]) - float(previous_bar["open_interest"])

        previous_main = db.query(
            """
            SELECT contract, trading_date FROM contract_master
            WHERE product_code=? AND is_main=1 AND trading_date<?
            ORDER BY trading_date DESC LIMIT 1
            """,
            (code, str(main["trading_date"])),
        )
        if previous_main and previous_main[0]["contract"] != contract:
            item["main_switch_from"] = previous_main[0]["contract"]
            anomalies.append(
                {
                    "severity": "info",
                    "code": "main_contract_switch",
                    "product": code,
                    "message": f"{name} 主力从 {previous_main[0]['contract']} 切换为 {contract}",
                }
            )

        position_date = _latest_table_date(db, "positions", "trading_date", requested_date)
        position = None
        if position_date:
            position_rows = db.query(
                """
                SELECT * FROM positions
                WHERE product_code=? AND trading_date=?
                ORDER BY CASE side WHEN 'long' THEN 1 WHEN 'short' THEN 2 ELSE 3 END, rank
                """,
                (code, position_date),
            )
            if position_rows:
                long_total = sum(
                    float(row["position"]) for row in position_rows if row["side"] == "long"
                )
                short_total = sum(
                    float(row["position"]) for row in position_rows if row["side"] == "short"
                )
                position = {
                    "trading_date": position_date,
                    "contract": position_rows[0]["contract"],
                    "long_total": long_total,
                    "short_total": short_total,
                    "net_total": long_total - short_total,
                    "top_long_changes": [
                        dict(row) for row in position_rows if row["side"] == "long"
                    ][:3],
                    "top_short_changes": [
                        dict(row) for row in position_rows if row["side"] == "short"
                    ][:3],
                }
        item["position"] = position
        if position is None:
            anomalies.append(
                {
                    "severity": "warning",
                    "code": "missing_position",
                    "product": code,
                    "message": f"{name} 未找到持仓排名数据",
                }
            )
        elif position["contract"] != contract:
            anomalies.append(
                {
                    "severity": "warning",
                    "code": "position_contract_mismatch",
                    "product": code,
                    "message": (
                        f"{name} 报告主力为 {contract}，持仓口径为 {position['contract']}；"
                        "两者不得混用"
                    ),
                }
            )

        basis_rows = db.query(
            """
            SELECT * FROM basis_history
            WHERE product_code=? AND quote_date<=?
            ORDER BY quote_date DESC, fetched_at DESC LIMIT 1
            """,
            (code, requested_date),
        )
        basis = dict(basis_rows[0]) if basis_rows else None
        if basis:
            history = [
                float(row["basis_value"])
                for row in db.query(
                    """
                    SELECT basis_value FROM basis_history
                    WHERE product_code=? AND quote_date<=? AND basis_value IS NOT NULL
                    ORDER BY quote_date
                    """,
                    (code, requested_date),
                )
            ]
            current = float(basis["basis_value"])
            basis["percentile"] = (
                sum(1 for value in history if value <= current) / len(history) * 100
                if history
                else None
            )
            previous_basis = db.query(
                """
                SELECT basis_value FROM basis_history
                WHERE product_code=? AND quote_date<?
                ORDER BY quote_date DESC LIMIT 1
                """,
                (code, basis["quote_date"]),
            )
            basis["change"] = (
                current - float(previous_basis[0]["basis_value"])
                if previous_basis and previous_basis[0]["basis_value"] is not None
                else None
            )
            if basis["contract"] != contract:
                anomalies.append(
                    {
                        "severity": "warning",
                        "code": "basis_contract_mismatch",
                        "product": code,
                        "message": (
                            f"{name} 报告主力为 {contract}，基差口径为 {basis['contract']}；"
                            "主连切换日基差会出现跳变"
                        ),
                    }
                )
        item["basis"] = basis
        if basis is None:
            anomalies.append(
                {
                    "severity": "warning",
                    "code": "missing_basis",
                    "product": code,
                    "message": f"{name} 未找到基差数据",
                }
            )

        products.append(item)

    coal_date = _latest_table_date(db, "coal_prices", "quote_date", requested_date)
    coal = []
    if coal_date:
        coal = [
            dict(row)
            for row in db.query(
                "SELECT * FROM coal_prices WHERE quote_date=? ORDER BY benchmark",
                (coal_date,),
            )
        ]
    else:
        anomalies.append(
            {
                "severity": "warning",
                "code": "missing_coal",
                "message": "未找到煤价数据",
            }
        )

    news_rows = db.query(
        """
        SELECT * FROM news_items
        WHERE substr(COALESCE(published_at, first_seen_at), 1, 10) <= ?
        ORDER BY COALESCE(published_at, first_seen_at) DESC LIMIT 12
        """,
        (requested_date,),
    )
    news = [dict(row) for row in news_rows]

    critical = any(item["severity"] == "error" for item in anomalies)
    has_market = any(not product.get("missing") for product in products)
    if not has_market:
        status = "failed"
    elif critical:
        status = "partial"
    else:
        status = "success"

    return {
        "trading_date": requested_date,
        "effective_market_date": effective_market_date,
        "generated_at": datetime.now(SHANGHAI).isoformat(timespec="seconds"),
        "status": status,
        "products": products,
        "coal_date": coal_date,
        "coal": coal,
        "news": news,
        "anomalies": anomalies,
    }

def render_brief(context: Mapping[str, Any]) -> str:
    lines: list[str] = [
        f"# 期货资讯日报 {context['trading_date']}",
        "",
        f"> 生成时间：{context['generated_at']}  ",
        f"> 行情数据截至：{context['effective_market_date']}  ",
        f"> 运行状态：{context['status']}",
        "",
        "## 市场概况",
        "",
        "| 品种 | 报告合约 | 收盘 | 涨跌 | 结算 | 成交量 | 持仓量 | MA20 |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    products = context["products"]
    for item in products:
        if item.get("missing"):
            lines.append(f"| {item['name']} | - | - | - | - | - | - | - |")
            continue
        bar = item["bar"]
        lines.append(
            "| {name} | {contract} | {close} | {change} | {settle} | {volume} | {oi} | {ma20} |".format(
                name=item["name"],
                contract=item["contract"],
                close=_fmt(bar.get("close")),
                change=_pct(item.get("change_pct")),
                settle=_fmt(bar.get("settlement")),
                volume=_fmt(bar.get("volume"), 0),
                oi=_fmt(bar.get("open_interest"), 0),
                ma20=_fmt(item.get("ma20")),
            )
        )

    lines.extend(["", "## 品种摘要", ""])
    for item in products:
        if item.get("missing"):
            lines.append(f"### {item['name']}")
            lines.append("- 数据暂缺，详见异常清单。")
            lines.append("")
            continue
        bar = item["bar"]
        lines.append(f"### {item['name']} {item['contract']}")
        lines.append(
            f"- 行情：收盘 {_fmt(bar.get('close'))}，涨跌 {_pct(item.get('change_pct'))}，"
            f"结算 {_fmt(bar.get('settlement'))}，成交 {_fmt(bar.get('volume'), 0)} 手，"
            f"持仓 {_fmt(bar.get('open_interest'), 0)} 手。"
        )
        if item.get("oi_change") is not None or item.get("volume_change") is not None:
            lines.append(
                f"- 变化：持仓 {_fmt(item.get('oi_change'), 0)} 手，"
                f"成交量 {_pct(item.get('volume_change'))}。"
            )
        lines.append(
            f"- 均线：MA5 {_fmt(item.get('ma5'))}，MA10 {_fmt(item.get('ma10'))}，"
            f"MA20 {_fmt(item.get('ma20'))}，MA60 {_fmt(item.get('ma60'))}。"
        )
        position = item.get("position")
        if position:
            lines.append(
                f"- 持仓结构：{position['contract']} 前20多头 {_fmt(position['long_total'], 0)} 手，"
                f"前20空头 {_fmt(position['short_total'], 0)} 手，"
                f"净头寸 {_fmt(position['net_total'], 0)} 手，数据日 {position['trading_date']}。"
            )
        basis = item.get("basis")
        if basis:
            basis_text = (
                f"- 基差：{_fmt(basis.get('basis_value'))}，"
                f"合约 {basis.get('contract')}，数据日 {basis.get('quote_date')}。"
            )
            if basis.get("spot_price") is not None and basis.get("futures_price") is not None:
                basis_text += (
                    f" 期货价 {_fmt(basis.get('futures_price'))}，"
                    f"推导现货价 {_fmt(basis.get('spot_price'))}。"
                )
            if basis.get("percentile") is not None:
                basis_text += f" 历史分位 {_fmt(basis.get('percentile'), 1)}%。"
            lines.append(basis_text)
        if item.get("main_switch_from"):
            lines.append(f"- 主力切换：由 {item['main_switch_from']} 切换为 {item['contract']}。")
        lines.append("")

    if context["coal"]:
        lines.extend(["## 煤价", ""])
        for row in context["coal"]:
            lines.append(
                f"- {row['benchmark']}：{_fmt(row.get('price'))} {row.get('unit', '元/吨')}，"
                f"数据日 {row['quote_date']}。"
            )
        lines.append("")

    if context["news"]:
        lines.extend(["## 新闻要点", ""])
        for row in context["news"]:
            date_text = str(row.get("published_at") or "")[:10]
            lines.append(f"- [{date_text}] {row['title']}（{row['source']}）")
        lines.append("")

    lines.extend(["## 数据质量", ""])
    if context["anomalies"]:
        for anomaly in context["anomalies"]:
            lines.append(f"- [{anomaly['severity']}] {anomaly['message']}")
    else:
        lines.append("- 未发现异常。")
    lines.append("")
    lines.append("> OpenClaw默认只读取本简报和 anomalies.json；完整数据请按需查询SQLite。")
    lines.append("")
    return "\n".join(lines)

def render_html(context: Mapping[str, Any], brief: str) -> str:
    cards: list[str] = []
    for item in context["products"]:
        if item.get("missing"):
            body = "<p>数据暂缺</p>"
        else:
            body = (
                f"<strong>{html.escape(item['contract'])}</strong>"
                f"<span>{_fmt(item['bar'].get('close'))}</span>"
                f"<small>{_pct(item.get('change_pct'))}</small>"
            )
        cards.append(
            f"<section class='card'><h2>{html.escape(item['name'])}</h2>{body}</section>"
        )
    anomaly_items = "".join(
        f"<li><b>{html.escape(item['severity'])}</b> {html.escape(item['message'])}</li>"
        for item in context["anomalies"]
    ) or "<li>未发现异常</li>"
    return f'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>期货资讯日报 {html.escape(context['trading_date'])}</title>
<style>
body{{font-family:"Microsoft YaHei",sans-serif;margin:0;background:#f5f7fa;color:#142033}}
main{{max-width:1040px;margin:0 auto;padding:32px 20px 64px}}
h1{{margin-bottom:6px}} .meta{{color:#5a667a;margin-bottom:24px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:20px 0}}
.card{{background:#fff;border:1px solid #dfe6ef;border-radius:12px;padding:16px;box-shadow:0 4px 16px #1b35500a}}
.card h2{{font-size:16px;margin:0 0 10px}} .card strong{{display:block;color:#5a667a}}
.card span{{display:block;font-size:28px;font-weight:700;margin-top:4px}} .card small{{color:#d13b3b}}
.anomalies{{background:#fff;border-left:4px solid #e9a23b;padding:16px 20px;border-radius:8px}}
pre{{white-space:pre-wrap;background:#fff;border:1px solid #dfe6ef;border-radius:12px;padding:20px;line-height:1.65}}
</style>
</head>
<body><main>
<h1>期货资讯日报 {html.escape(context['trading_date'])}</h1>
<div class="meta">生成：{html.escape(context['generated_at'])} ｜ 行情截至：{html.escape(context['effective_market_date'])} ｜ 状态：{html.escape(context['status'])}</div>
<div class="cards">{''.join(cards)}</div>
<section class="anomalies"><h2>异常与口径提示</h2><ul>{anomaly_items}</ul></section>
<h2>完整简报</h2><pre>{html.escape(brief)}</pre>
</main></body></html>'''

def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temp.write_bytes(data)
    os.replace(temp, path)


def generate_daily_report(
    db: MarketDB,
    config: Mapping[str, Any],
    trading_date: str | None = None,
) -> dict[str, Any]:
    db.initialize()
    context = build_report_context(db, config, trading_date)
    brief = render_brief(context)
    report_html = render_html(context, brief)
    anomalies = {
        "trading_date": context["trading_date"],
        "generated_at": context["generated_at"],
        "items": context["anomalies"],
    }

    manifest: dict[str, Any] = {
        "schema_version": "1",
        "report_type": "futures-daily-brief",
        "trading_date": context["trading_date"],
        "effective_market_date": context["effective_market_date"],
        "generated_at": context["generated_at"],
        "status": context["status"],
        "default_openclaw_files": list(
            config.get("openclaw", {}).get(
                "default_files", ["manifest.json", "daily-brief.md", "anomalies.json"]
            )
        ),
        "products": [
            {
                "code": item["code"],
                "name": item["name"],
                "contract": item.get("contract"),
                "missing": bool(item.get("missing")),
            }
            for item in context["products"]
        ],
        "anomaly_count": len(context["anomalies"]),
    }

    report_root = Path(config["reports_dir"])
    final_dir = report_root / context["trading_date"]
    final_dir.mkdir(parents=True, exist_ok=True)
    success_path = final_dir / "success.ok"
    success_path.unlink(missing_ok=True)

    files = {
        "daily-brief.md": brief.encode("utf-8"),
        "anomalies.json": (
            json.dumps(anomalies, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8"),
        "report.html": report_html.encode("utf-8"),
    }
    manifest["files"] = [
        {"name": name, "bytes": len(data), "sha256": _sha256_bytes(data)}
        for name, data in sorted(files.items())
    ]
    files["manifest.json"] = (
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")

    for name, data in files.items():
        _atomic_write(final_dir / name, data)
    success_path.write_text(context["generated_at"] + "\n", encoding="utf-8")

    latest_pointer = {
        "trading_date": context["trading_date"],
        "report_dir": str(final_dir),
        "manifest": str(final_dir / "manifest.json"),
        "updated_at": context["generated_at"],
    }
    _atomic_write(
        report_root / "latest.json",
        (json.dumps(latest_pointer, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )

    db.record_report_run(
        context["trading_date"],
        str(final_dir),
        context["status"],
        json.dumps(manifest, ensure_ascii=False),
        context["generated_at"],
    )
    return {
        "status": context["status"],
        "trading_date": context["trading_date"],
        "report_dir": str(final_dir),
        "manifest": str(final_dir / "manifest.json"),
        "anomaly_count": len(context["anomalies"]),
    }
