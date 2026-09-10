from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from .config import DEFAULT_CONFIG, default_project_root


APP_DIR_NAME = "FuturesIntelTool"
PRODUCT_CODE_RE = re.compile(r"^[A-Z]{1,4}$")
CONTRACT_RE = re.compile(r"^[A-Z]{1,4}\d{4}$")


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def desktop_data_root() -> Path:
    if is_frozen():
        local = os.environ.get("LOCALAPPDATA")
        base = Path(local) if local else Path.home() / "AppData" / "Local"
        return (base / APP_DIR_NAME).resolve()
    return default_project_root().resolve()


def desktop_config_path() -> Path:
    root = desktop_data_root()
    return root / "config" / "default.json"


def prepare_desktop_environment() -> tuple[Path, Path]:
    root = desktop_data_root()
    config_path = desktop_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "reports").mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(parents=True, exist_ok=True)

    if not config_path.exists():
        config = json.loads(json.dumps(DEFAULT_CONFIG))
        config_path.write_text(
            json.dumps(config, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    holiday_path = root / "config" / "market_holidays.txt"
    if not holiday_path.exists():
        resource = Path(__file__).resolve().parent / "resources" / "market_holidays.txt"
        if resource.exists():
            holiday_path.write_text(resource.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            holiday_path.write_text("", encoding="utf-8")
    return root, config_path


def normalize_product(record: Mapping[str, Any]) -> dict[str, Any]:
    code = str(record.get("code") or "").strip().upper()
    name = str(record.get("name") or "").strip()
    exchange = str(record.get("exchange") or "").strip().upper()
    contract = str(record.get("contract_override") or record.get("contract") or "").strip().upper()
    mode = str(record.get("mode") or ("fixed" if contract else "auto")).strip().lower()

    if not PRODUCT_CODE_RE.fullmatch(code):
        raise ValueError("品种代码只能使用 1-4 个英文字母")
    if not name:
        raise ValueError("品种名称不能为空")
    if mode not in {"auto", "fixed"}:
        raise ValueError("合约模式必须为 auto 或 fixed")
    if mode == "fixed":
        if not CONTRACT_RE.fullmatch(contract):
            raise ValueError(f"{code} 的固定合约格式无效，例如 SH2701")
        if not contract.startswith(code):
            raise ValueError(f"{code} 的合约必须以品种代码开头")
    else:
        contract = ""

    product: dict[str, Any] = {
        "code": code,
        "name": name,
        "exchange": exchange,
    }
    if contract:
        product["contract_override"] = contract
    return product


def validate_products(products: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in products:
        product = normalize_product(record)
        if product["code"] in seen:
            raise ValueError(f"品种代码重复：{product['code']}")
        seen.add(product["code"])
        normalized.append(product)
    if not normalized:
        raise ValueError("至少需要保留一个品种")
    return normalized


def save_products(config_path: str | Path, products: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    path = Path(config_path)
    payload: dict[str, Any] = {}
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
    payload["products"] = validate_products(products)
    temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temp, path)
    return payload["products"]
