from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from .http import fetch_bytes
from .sina import normalize_contract_code


SHANGHAI = ZoneInfo("Asia/Shanghai")
BASE_URL = "https://www.jiaoyifamen.com/tools/api/"
HEADERS = {"Referer": "https://www.jiaoyifamen.com/variety/"}
SOURCE = "jiaoyifamen"


def _float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _fetch_json(path: str, timeout: float = 20.0) -> dict[str, Any]:
    payload = fetch_bytes(BASE_URL + path, headers=HEADERS, timeout=timeout)
    decoded = json.loads(payload.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError(f"unexpected response from {path}")
    if decoded.get("code") != 200:
        raise ValueError(f"source error from {path}: {decoded.get('message')}")
    return decoded


def fetch_position(product_code: str, *, timeout: float = 20.0) -> dict[str, Any]:
    return _fetch_json(f"position/details/{product_code.upper()}", timeout=timeout)


def fetch_basis(product_code: str, *, timeout: float = 20.0) -> dict[str, Any]:
    return _fetch_json(f"future-basis/query?type={product_code.upper()}", timeout=timeout)


def parse_position_payload(
    payload: Mapping[str, Any],
    *,
    product_code: str,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise ValueError("position payload is missing data")

    raw_tables = [
        ("long", data.get("long_rank_table") or []),
        ("short", data.get("short_rank_table") or []),
        ("net_long", data.get("net_long_rank_table") or []),
        ("net_short", data.get("net_short_rank_table") or []),
    ]

    day_text = ""
    for _, table in raw_tables:
        if table:
            day_text = str(table[0].get("day") or "")
            if day_text:
                break
    if not day_text:
        raise ValueError("position payload does not contain a trading day")
    trading_date = day_text[:10]
    raw_contract = str(data.get("instrument") or "")
    if not raw_contract:
        raise ValueError("position payload does not contain instrument")
    contract = normalize_contract_code(raw_contract, trading_date)
    stamp = fetched_at or datetime.now(SHANGHAI).isoformat(timespec="seconds")

    rows: list[dict[str, Any]] = []
    totals: dict[str, float] = {}
    for side, table in raw_tables:
        total = 0.0
        for item in table:
            if not isinstance(item, Mapping):
                continue
            member = str(item.get("memberName") or "").strip()
            position = _float(item.get("indicator"))
            if not member or position is None:
                continue
            total += position
            rows.append(
                {
                    "trading_date": trading_date,
                    "product_code": product_code.upper(),
                    "contract": contract,
                    "member": member,
                    "side": side,
                    "rank": int(item["rank"]) if item.get("rank") is not None else None,
                    "position": position,
                    "change": _float(item.get("indicatorIncrease")),
                    "source": SOURCE,
                    "fetched_at": stamp,
                }
            )
        totals[side] = total

    return {
        "trading_date": trading_date,
        "product_code": product_code.upper(),
        "contract": contract,
        "future_name": str(data.get("futureName") or ""),
        "long_total": totals.get("long", 0.0),
        "short_total": totals.get("short", 0.0),
        "net_total": totals.get("long", 0.0) - totals.get("short", 0.0),
        "positions": rows,
        "source": SOURCE,
    }


def parse_basis_payload(
    payload: Mapping[str, Any],
    *,
    product_code: str,
    contract: str,
    fetched_at: str | None = None,
) -> list[dict[str, Any]]:
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise ValueError("basis payload is missing data")

    dates = data.get("category") or data.get("dateList") or []
    values = data.get("basisValue") or []
    futures_prices = data.get("priceValue") or []
    if not isinstance(dates, list) or not isinstance(values, list):
        raise ValueError("basis dates and basisValue must be lists")
    if len(dates) != len(values):
        raise ValueError("basis dates and basisValue lengths differ")
    if futures_prices and len(futures_prices) != len(values):
        futures_prices = []

    stamp = fetched_at or datetime.now(SHANGHAI).isoformat(timespec="seconds")
    rows: list[dict[str, Any]] = []
    for index, (quote_date, value) in enumerate(zip(dates, values)):
        basis_value = _float(value)
        if basis_value is None:
            continue
        quote_date = str(quote_date)[:10]
        if not quote_date:
            continue
        futures_price = (
            _float(futures_prices[index]) if futures_prices else None
        )
        spot_price = (
            futures_price + basis_value if futures_price is not None else None
        )
        rows.append(
            {
                "quote_date": quote_date,
                "product_code": product_code.upper(),
                "contract": contract.upper(),
                "definition_id": "jiaoyifamen_main_basis_v1",
                "basis_value": basis_value,
                "spot_price": spot_price,
                "futures_price": futures_price,
                "source": SOURCE,
                "fetched_at": stamp,
            }
        )
    return rows
