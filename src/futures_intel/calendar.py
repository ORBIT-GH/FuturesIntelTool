from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo


SHANGHAI = ZoneInfo("Asia/Shanghai")


def load_holidays(config: Mapping[str, Any]) -> set[str]:
    raw_path = config.get("market_holidays_file")
    if not raw_path:
        return set()
    path = Path(raw_path)
    if not path.is_absolute():
        path = Path(config.get("project_root", ".")) / path
    if not path.exists():
        return set()
    holidays: set[str] = set()
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        holidays.add(line)
    return holidays


def is_trading_day(value: date | datetime | str | None, config: Mapping[str, Any]) -> bool:
    if value is None:
        day = datetime.now(SHANGHAI).date()
    elif isinstance(value, datetime):
        day = value.date()
    elif isinstance(value, date):
        day = value
    else:
        day = date.fromisoformat(value[:10])
    if day.weekday() >= 5:
        return False
    return day.isoformat() not in load_holidays(config)
