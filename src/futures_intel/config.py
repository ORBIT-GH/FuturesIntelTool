from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


DEFAULT_CONFIG: dict[str, Any] = {
    "timezone": "Asia/Shanghai",
    "market_holidays_file": "config/market_holidays.txt",
    "database": "data/market.sqlite",
    "reports_dir": "reports",
    "logs_dir": "logs",
    "history_days": 180,
    "contract_months_ahead": 20,
    "products": [
        {"code": "SH", "name": "烧碱", "exchange": "CZCE"},
        {"code": "V", "name": "PVC", "exchange": "DCE"},
        {"code": "JM", "name": "焦煤", "exchange": "DCE"},
        {"code": "M", "name": "豆粕", "exchange": "DCE"},
    ],
    "rss_feeds": [],
    "news_keywords": {
        "SH": ["烧碱", "液碱", "片碱", "氯碱"],
        "V": ["PVC", "聚氯乙烯", "电石"],
        "JM": ["焦煤", "炼焦煤", "煤炭"],
        "M": ["豆粕", "大豆", "CBOT大豆"],
    },
    "openclaw": {
        "default_files": ["manifest.json", "daily-brief.md", "anomalies.json"]
    },
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def default_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_config_path(path: str | Path | None = None) -> Path:
    if path is not None:
        return Path(path).expanduser().resolve()
    candidate = default_project_root() / "config" / "default.json"
    return candidate.resolve()


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    config_path = resolve_config_path(path)
    root = config_path.parent.parent
    override: dict[str, Any] = {}
    if config_path.exists():
        override = json.loads(config_path.read_text(encoding="utf-8"))
    config = _deep_merge(DEFAULT_CONFIG, override)

    config["config_path"] = str(config_path)
    config["project_root"] = str(root)
    for key in ("database", "reports_dir", "logs_dir"):
        value = Path(config[key]).expanduser()
        if not value.is_absolute():
            value = root / value
        config[key] = str(value.resolve())

    if not isinstance(config.get("products"), list) or not config["products"]:
        raise ValueError("config.products must be a non-empty list")

    seen: set[str] = set()
    for product in config["products"]:
        code = str(product.get("code", "")).strip().upper()
        name = str(product.get("name", "")).strip()
        if not code or not name:
            raise ValueError("each product requires code and name")
        if code in seen:
            raise ValueError(f"duplicate product code: {code}")
        seen.add(code)
        product["code"] = code

    return config


def ensure_runtime_dirs(config: dict[str, Any]) -> None:
    Path(config["database"]).parent.mkdir(parents=True, exist_ok=True)
    Path(config["reports_dir"]).mkdir(parents=True, exist_ok=True)
    Path(config["logs_dir"]).mkdir(parents=True, exist_ok=True)
