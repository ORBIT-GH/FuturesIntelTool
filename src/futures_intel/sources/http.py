from __future__ import annotations

from typing import Mapping
from urllib.request import Request, urlopen


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def fetch_bytes(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float = 20.0,
) -> bytes:
    request_headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if headers:
        request_headers.update(headers)
    request = Request(url, headers=request_headers)
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def fetch_text(
    url: str,
    *,
    encoding: str = "utf-8",
    headers: Mapping[str, str] | None = None,
    timeout: float = 20.0,
) -> str:
    return fetch_bytes(url, headers=headers, timeout=timeout).decode(
        encoding, errors="replace"
    )
