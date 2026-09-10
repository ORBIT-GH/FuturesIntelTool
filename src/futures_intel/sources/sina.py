from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from .http import fetch_bytes


SHANGHAI = ZoneInfo("Asia/Shanghai")
CONTRACT_RE = re.compile(r"^(?P<product>[A-Z]+)(?P<month>\d{3,4})$")
QUOTE_RE = re.compile(r'var\s+hq_str_nf_(?P<symbol>[A-Z0-9]+)="(?P<body>[^"]*)";')


@dataclass(frozen=True, slots=True)
class ContractQuote:
    trading_date: str
    product_code: str
    contract: str
    name: str
    open: float | None
    high: float | None
    low: float | None
    last: float | None
    settlement: float | None
    previous_settlement: float | None
    volume: float | None
    open_interest: float | None
    source: str
    fetched_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "trading_date": self.trading_date,
            "product_code": self.product_code,
            "contract": self.contract,
            "name": self.name,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "last": self.last,
            "settlement": self.settlement,
            "previous_settlement": self.previous_settlement,
            "volume": self.volume,
            "open_interest": self.open_interest,
            "source": self.source,
            "fetched_at": self.fetched_at,
        }


def _float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "null", "none", "--"}:
        return None
    try:
        number = float(text.replace(",", ""))
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def normalize_contract_code(raw_code: str, as_of: str | date | datetime) -> str:
    if isinstance(as_of, str):
        as_of_date = date.fromisoformat(as_of[:10])
    elif isinstance(as_of, datetime):
        as_of_date = as_of.date()
    else:
        as_of_date = as_of

    match = CONTRACT_RE.match(raw_code.strip().upper())
    if not match:
        raise ValueError(f"invalid futures contract code: {raw_code}")

    product = match.group("product")
    month_text = match.group("month")
    if len(month_text) == 4:
        return f"{product}{month_text}"

    year_digit = int(month_text[0])
    month = int(month_text[1:])
    if month < 1 or month > 12:
        raise ValueError(f"invalid contract month: {raw_code}")

    decade = (as_of_date.year // 10) * 10
    year = decade + year_digit
    if year < as_of_date.year - 2:
        year += 10
    elif year > as_of_date.year + 8:
        year -= 10
    return f"{product}{year % 100:02d}{month:02d}"


def candidate_contracts(
    product_code: str,
    as_of: str | date | datetime,
    months_ahead: int = 20,
) -> list[str]:
    if isinstance(as_of, str):
        base = date.fromisoformat(as_of[:10])
    elif isinstance(as_of, datetime):
        base = as_of.date()
    else:
        base = as_of
    contracts: list[str] = []
    year, month = base.year, base.month
    for offset in range(months_ahead + 1):
        index = (month - 1) + offset
        contract_year = year + index // 12
        contract_month = index % 12 + 1
        contracts.append(f"{product_code.upper()}{contract_year % 100:02d}{contract_month:02d}")
    return contracts


def parse_sina_quotes(
    text: str,
    *,
    fetched_at: str | None = None,
    default_trading_date: str | None = None,
) -> list[ContractQuote]:
    stamp = fetched_at or datetime.now(SHANGHAI).isoformat(timespec="seconds")
    quotes: list[ContractQuote] = []
    for match in QUOTE_RE.finditer(text):
        contract = match.group("symbol").upper()
        fields = match.group("body").split(",")
        if len(fields) < 18 or not fields[8]:
            continue
        product_match = re.match(r"^([A-Z]+)", contract)
        if not product_match:
            continue
        trading_date = fields[17][:10] if fields[17] else default_trading_date
        if not trading_date:
            continue
        quotes.append(
            ContractQuote(
                trading_date=trading_date,
                product_code=product_match.group(1),
                contract=contract,
                name=fields[0].strip(),
                open=_float(fields[2]),
                high=_float(fields[3]),
                low=_float(fields[4]),
                last=_float(fields[8]),
                settlement=_float(fields[9]),
                previous_settlement=_float(fields[10]),
                open_interest=_float(fields[13]),
                volume=_float(fields[14]),
                source="sina",
                fetched_at=stamp,
            )
        )
    return quotes


def choose_main_contract(
    quotes: Iterable[ContractQuote | Mapping[str, Any]],
    product_code: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    product = product_code.upper()
    for quote in quotes:
        item = quote.as_dict() if isinstance(quote, ContractQuote) else dict(quote)
        if str(item.get("product_code", "")).upper() != product:
            continue
        oi = _float(item.get("open_interest"))
        volume = _float(item.get("volume"))
        if oi is None or oi <= 0:
            continue
        rows.append(item)

    rows.sort(
        key=lambda row: (
            _float(row.get("open_interest")) or 0.0,
            _float(row.get("volume")) or 0.0,
        ),
        reverse=True,
    )
    result: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        row["rank"] = index
        row["is_main"] = 1 if index == 1 else 0
        row["rule_version"] = "v1_oi_then_volume"
        result.append(row)
    return result


def fetch_quotes(
    contracts: Iterable[str],
    *,
    fetched_at: str | None = None,
    timeout: float = 20.0,
) -> list[ContractQuote]:
    symbols = [contract.upper() for contract in contracts if contract]
    if not symbols:
        return []
    url = "https://hq.sinajs.cn/list=" + ",".join(f"nf_{symbol}" for symbol in symbols)
    payload = fetch_bytes(
        url,
        headers={"Referer": "https://finance.sina.com.cn/"},
        timeout=timeout,
    )
    return parse_sina_quotes(
        payload.decode("gb18030", errors="replace"),
        fetched_at=fetched_at,
    )


def parse_daily_kline_jsonp(
    text: str,
    *,
    product_code: str,
    contract: str,
    source: str = "sina",
    fetched_at: str | None = None,
    session: str = "full",
) -> list[dict[str, Any]]:
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end <= start:
        raise ValueError("daily K-line response does not contain a JSON array")
    payload = json.loads(text[start : end + 1])
    if not isinstance(payload, list):
        raise ValueError("daily K-line payload must be a list")

    stamp = fetched_at or datetime.now(SHANGHAI).isoformat(timespec="seconds")
    rows: list[dict[str, Any]] = []
    previous_settlement: float | None = None
    for bar in payload:
        if not isinstance(bar, Mapping):
            continue
        trading_date = str(bar.get("d", ""))[:10]
        if not trading_date:
            continue
        settlement = _float(bar.get("s"))
        rows.append(
            {
                "trading_date": trading_date,
                "product_code": product_code.upper(),
                "contract": contract.upper(),
                "period": "1d",
                "session": session,
                "open": _float(bar.get("o")),
                "high": _float(bar.get("h")),
                "low": _float(bar.get("l")),
                "close": _float(bar.get("c")),
                "settlement": settlement,
                "previous_settlement": previous_settlement,
                "volume": _float(bar.get("v")),
                "open_interest": _float(bar.get("p")),
                "source": source,
                "fetched_at": stamp,
            }
        )
        previous_settlement = settlement
    return rows


def fetch_daily_kline(
    contract: str,
    *,
    product_code: str | None = None,
    fetched_at: str | None = None,
    timeout: float = 20.0,
) -> list[dict[str, Any]]:
    symbol = contract.upper()
    product_match = re.match(r"^[A-Z]+", symbol)
    if product_code:
        product = product_code.upper()
    elif product_match:
        product = product_match.group(0)
    else:
        raise ValueError(f"cannot infer product from contract: {contract}")
    url = (
        "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/"
        f"var%20_X=/InnerFuturesNewService.getDailyKLine?symbol={symbol}"
    )
    payload = fetch_bytes(
        url,
        headers={"Referer": "https://finance.sina.com.cn/"},
        timeout=timeout,
    )
    return parse_daily_kline_jsonp(
        payload.decode("utf-8", errors="replace"),
        product_code=product,
        contract=symbol,
        fetched_at=fetched_at,
    )
