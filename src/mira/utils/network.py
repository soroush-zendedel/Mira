"""Network helpers using only stdlib."""

from __future__ import annotations

import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Optional

from mira.constants import DEFAULT_CONNECT_TIMEOUT, DEFAULT_READ_TIMEOUT
from mira.exceptions import NetworkError, ValidationError

ProgressCallback = Callable[[int, Optional[int]], None]


def validate_url(url: str, allowed_schemes: tuple[str, ...] = ("https",)) -> urllib.parse.ParseResult:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in allowed_schemes:
        raise ValidationError(
            f"URL scheme not allowed: {parsed.scheme!r} (allowed: {allowed_schemes})"
        )
    if not parsed.netloc:
        raise ValidationError(f"Invalid URL (missing host): {url}")
    return parsed


def _parse_content_length(headers) -> Optional[int]:
    try:
        if not headers:
            return None
        raw = headers.get("Content-Length") or headers.get("content-length")
        if raw is None:
            return None
        return int(raw)
    except (TypeError, ValueError):
        return None


def fetch_url(
    url: str,
    *,
    timeout: float = DEFAULT_CONNECT_TIMEOUT,
    read_timeout: float = DEFAULT_READ_TIMEOUT,
    headers: Optional[dict] = None,
    method: str = "GET",
    data: Optional[bytes] = None,
    max_size: int = 2 * 1024 * 1024,
    progress: Optional[ProgressCallback] = None,
    chunk_size: int = 64 * 1024,
) -> tuple[int, dict, bytes, float]:
    """
    Fetch a URL and return (status_code, headers_dict, body, latency_ms).
    Optional progress(bytes_received, total_or_None) is called during body download.
    """
    validate_url(url)
    req_headers = {
        "User-Agent": "Mira/1.0 (Repository Mirror Manager)",
        "Accept": "*/*",
    }
    if headers:
        req_headers.update(headers)

    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout + read_timeout) as resp:
            status = getattr(resp, "status", None) or resp.getcode()
            hdrs = dict(resp.headers.items()) if resp.headers else {}
            total = _parse_content_length(resp.headers)
            chunks: list[bytes] = []
            received = 0
            while True:
                to_read = chunk_size
                if max_size is not None:
                    remaining = max_size + 1 - received
                    if remaining <= 0:
                        break
                    to_read = min(to_read, remaining)
                piece = resp.read(to_read)
                if not piece:
                    break
                chunks.append(piece)
                received += len(piece)
                if progress is not None:
                    try:
                        progress(received, total)
                    except Exception:
                        pass
                if max_size is not None and received > max_size:
                    raise NetworkError(f"Response too large (> {max_size} bytes)")
            body = b"".join(chunks)
            if progress is not None:
                try:
                    progress(received, total if total is not None else received)
                except Exception:
                    pass
            latency_ms = (time.perf_counter() - start) * 1000.0
            return int(status), hdrs, body, latency_ms
    except urllib.error.HTTPError as e:
        latency_ms = (time.perf_counter() - start) * 1000.0
        body = b""
        try:
            body = e.read(max_size)
        except Exception:
            pass
        return int(e.code), dict(e.headers.items()) if e.headers else {}, body, latency_ms
    except urllib.error.URLError as e:
        raise NetworkError(f"URL error for {url}: {e.reason}") from e
    except socket.timeout as e:
        raise NetworkError(f"Timeout fetching {url}") from e
    except ssl.SSLError as e:
        raise NetworkError(f"SSL error for {url}: {e}") from e
    except OSError as e:
        raise NetworkError(f"OS/network error for {url}: {e}") from e


def head_or_get(
    url: str,
    *,
    timeout: float = DEFAULT_CONNECT_TIMEOUT,
    prefer_head: bool = True,
) -> tuple[int, dict, bytes, float]:
    if prefer_head:
        try:
            status, headers, body, latency = fetch_url(url, timeout=timeout, method="HEAD")
            if status < 400:
                return status, headers, body, latency
        except NetworkError:
            pass
    return fetch_url(url, timeout=timeout, method="GET")
