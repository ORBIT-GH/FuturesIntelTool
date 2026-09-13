from __future__ import annotations

import ssl
import time
from typing import Mapping
from urllib.error import HTTPError, URLError
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
    retries: int = 3,
    backoff: float = 1.0,
) -> bytes:
    if retries < 1:
        raise ValueError("retries must be at least 1")

    request_headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if headers:
        request_headers.update(headers)
    request = Request(url, headers=request_headers)
    last_error: Exception | None = None

    for attempt in range(retries):
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.read()
        except HTTPError as exc:
            last_error = exc
            if exc.code < 500 or attempt >= retries - 1:
                raise
        except (URLError, TimeoutError, ssl.SSLError, ConnectionError) as exc:
            last_error = exc
            if attempt >= retries - 1:
                raise
        if backoff > 0:
            time.sleep(backoff * (2**attempt))

    if last_error is not None:
        raise last_error
    raise RuntimeError(f"request failed without an exception: {url}")


def fetch_text(
    url: str,
    *,
    encoding: str = "utf-8",
    headers: Mapping[str, str] | None = None,
    timeout: float = 20.0,
    retries: int = 3,
    backoff: float = 1.0,
) -> str:
    return fetch_bytes(
        url,
        headers=headers,
        timeout=timeout,
        retries=retries,
        backoff=backoff,
    ).decode(encoding, errors="replace")
