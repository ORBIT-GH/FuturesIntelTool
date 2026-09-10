from __future__ import annotations

import json
import mimetypes
from datetime import date as date_type
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, urlparse

from .db import MarketDB
from .pipeline import Collector
from .report import build_report_context, generate_daily_report


STATIC_DIR = Path(__file__).resolve().parent / "web_static"


def _valid_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return date_type.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError("date must use YYYY-MM-DD") from exc


class DashboardService:
    def __init__(self, config: Mapping[str, Any], db: MarketDB):
        self.config = dict(config)
        self.db = db

    def summary(self, trading_date: str | None = None) -> dict[str, Any]:
        requested = _valid_date(trading_date)
        context = build_report_context(self.db, self.config, requested)
        latest_run = self.db.query(
            "SELECT * FROM collect_runs ORDER BY id DESC LIMIT 1"
        )
        return {
            "context": context,
            "latest_run": dict(latest_run[0]) if latest_run else None,
        }

    def runs(self, limit: int = 20) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.db.query(
                "SELECT * FROM collect_runs ORDER BY id DESC LIMIT ?",
                (max(1, min(limit, 200)),),
            )
        ]

    def health(self, run_id: int | None = None) -> list[dict[str, Any]]:
        if run_id is None:
            row = self.db.query("SELECT MAX(id) AS id FROM collect_runs")
            run_id = int(row[0]["id"]) if row and row[0]["id"] is not None else 0
        return [
            dict(row)
            for row in self.db.query(
                "SELECT * FROM source_health WHERE run_id=? ORDER BY id",
                (run_id,),
            )
        ]

    def market(
        self,
        trading_date: str | None = None,
        product: str | None = None,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        clauses = ["1=1"]
        params: list[Any] = []
        requested = _valid_date(trading_date)
        if requested:
            clauses.append("trading_date <= ?")
            params.append(requested)
        if product:
            clauses.append("product_code = ?")
            params.append(product.upper())
        params.append(max(1, min(limit, 500)))
        sql = f"""
            SELECT trading_date, product_code, contract, exchange, open_interest,
                   volume, rank, is_main, rule_version, fetched_at
            FROM contract_master
            WHERE {' AND '.join(clauses)}
            ORDER BY trading_date DESC, product_code, rank
            LIMIT ?
        """
        return [dict(row) for row in self.db.query(sql, params)]

    def report(self, trading_date: str | None = None) -> dict[str, Any]:
        requested = _valid_date(trading_date)
        if not requested:
            latest = self.db.scalar("SELECT MAX(trading_date) FROM futures_daily")
            requested = str(latest) if latest else None
        if not requested:
            return {"available": False, "trading_date": None}
        report_dir = Path(self.config["reports_dir"]) / requested
        brief_path = report_dir / "daily-brief.md"
        if not brief_path.exists():
            return {
                "available": False,
                "trading_date": requested,
                "report_dir": str(report_dir),
            }
        anomalies_path = report_dir / "anomalies.json"
        manifest_path = report_dir / "manifest.json"
        return {
            "available": True,
            "trading_date": requested,
            "report_dir": str(report_dir),
            "brief": brief_path.read_text(encoding="utf-8"),
            "anomalies": json.loads(anomalies_path.read_text(encoding="utf-8"))
            if anomalies_path.exists()
            else {"items": []},
            "manifest": json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest_path.exists()
            else {},
        }

    def run(self, trading_date: str | None = None) -> dict[str, Any]:
        requested = _valid_date(trading_date)
        collect_result = Collector(self.config, self.db).collect(requested)
        report_result = generate_daily_report(self.db, self.config, requested)
        return {
            "collect": collect_result.as_dict(),
            "report": report_result,
        }


class DashboardHandler(BaseHTTPRequestHandler):
    service: DashboardService

    def _json(self, payload: Any, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _static(self, path: str) -> None:
        name = "index.html" if path == "/" else path.lstrip("/")
        target = (STATIC_DIR / name).resolve()
        if STATIC_DIR.resolve() not in target.parents and target != STATIC_DIR.resolve():
            self._json({"error": "invalid path"}, 403)
            return
        if not target.is_file():
            self._json({"error": "not found"}, 404)
            return
        data = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if content_type.startswith("text/"):
            content_type += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        try:
            if parsed.path == "/":
                self._static("/")
                return
            if parsed.path in {"/app.js", "/styles.css"}:
                self._static(parsed.path)
                return
            if parsed.path == "/api/summary":
                self._json(self.service.summary(query.get("date", [None])[0]))
                return
            if parsed.path == "/api/runs":
                limit = int(query.get("limit", ["20"])[0])
                self._json(self.service.runs(limit))
                return
            if parsed.path == "/api/health":
                run_id = query.get("run_id", [None])[0]
                self._json(self.service.health(int(run_id) if run_id else None))
                return
            if parsed.path == "/api/market":
                limit = int(query.get("limit", ["30"])[0])
                self._json(
                    self.service.market(
                        query.get("date", [None])[0],
                        query.get("product", [None])[0],
                        limit,
                    )
                )
                return
            if parsed.path == "/api/report":
                self._json(self.service.report(query.get("date", [None])[0]))
                return
            self._json({"error": "not found"}, 404)
        except ValueError as exc:
            self._json({"error": str(exc)}, 400)
        except Exception as exc:
            self._json({"error": type(exc).__name__, "message": str(exc)}, 500)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/run":
            self._json({"error": "not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 1_000_000:
                raise ValueError("request body too large")
            payload = json.loads(self.rfile.read(length) or b"{}")
            self._json(self.service.run(payload.get("date")))
        except ValueError as exc:
            self._json({"error": str(exc)}, 400)
        except Exception as exc:
            self._json({"error": type(exc).__name__, "message": str(exc)}, 500)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[dashboard] {self.address_string()} {format % args}")


def serve_dashboard(config: Mapping[str, Any], host: str = "127.0.0.1", port: int = 8765) -> None:
    db = MarketDB(config["database"])
    db.initialize()
    service = DashboardService(config, db)

    class BoundHandler(DashboardHandler):
        pass

    BoundHandler.service = service
    server = ThreadingHTTPServer((host, port), BoundHandler)
    print(f"期货资讯看板已启动: http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
