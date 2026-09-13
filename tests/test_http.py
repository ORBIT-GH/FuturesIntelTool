from __future__ import annotations

import io
import ssl
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from futures_intel.sources.http import fetch_bytes


class FakeResponse:
    def __init__(self, data: bytes):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self.data


class HttpRetryTest(unittest.TestCase):
    def test_retries_ssl_timeout(self) -> None:
        errors = [URLError(ssl.SSLError("handshake operation timed out")), FakeResponse(b"ok")]
        with patch("futures_intel.sources.http.urlopen", side_effect=errors) as mocked:
            result = fetch_bytes("https://example.com", retries=2, backoff=0)
        self.assertEqual(b"ok", result)
        self.assertEqual(2, mocked.call_count)

    def test_does_not_retry_http_404(self) -> None:
        error = HTTPError("https://example.com", 404, "not found", {}, io.BytesIO())
        with patch("futures_intel.sources.http.urlopen", side_effect=error) as mocked:
            with self.assertRaises(HTTPError):
                fetch_bytes("https://example.com", retries=3, backoff=0)
        self.assertEqual(1, mocked.call_count)
        error.close()


if __name__ == "__main__":
    unittest.main()
