"""Network helpers using only stdlib."""

from __future__ import annotations

import os
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

# Common system CA bundle locations (Linux distros, macOS Homebrew, etc.).
# PyInstaller one-file builds often cannot locate OpenSSL's compiled-in defaults,
# which surfaces as CERTIFICATE_VERIFY_FAILED on otherwise healthy systems.
_SYSTEM_CA_CANDIDATES = (
    "/etc/ssl/certs/ca-certificates.crt",  # Debian/Ubuntu/Arch (ca-certificates)
    "/etc/pki/tls/certs/ca-bundle.crt",  # RHEL/CentOS/Fedora
    "/etc/ssl/cert.pem",  # Alpine, some BSDs, generic OpenSSL
    "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem",  # Fedora/RHEL trust extract
    "/usr/local/etc/openssl@3/cert.pem",  # Homebrew OpenSSL 3 (macOS)
    "/usr/local/etc/openssl/cert.pem",  # Homebrew OpenSSL
    "/etc/ssl/ca-bundle.pem",
)


def _iter_ca_file_candidates() -> list[str]:
    """Ordered list of CA bundle paths to try (env overrides first)."""
    candidates: list[str] = []
    for key in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        value = os.environ.get(key)
        if value:
            candidates.append(value)
    try:
        defaults = ssl.get_default_verify_paths()
        for path in (defaults.cafile, defaults.openssl_cafile):
            if path:
                candidates.append(path)
    except Exception:
        pass
    candidates.extend(_SYSTEM_CA_CANDIDATES)
    # De-duplicate while preserving order
    seen: set[str] = set()
    ordered: list[str] = []
    for path in candidates:
        if path not in seen:
            seen.add(path)
            ordered.append(path)
    return ordered


def build_ssl_context() -> ssl.SSLContext:
    """
    Build a verifying SSL context that works for both normal Python installs
    and frozen (PyInstaller) binaries on Linux.

    Never disables certificate verification. If no CA bundle can be loaded the
    returned context still uses the library defaults so the underlying error
    remains visible to the caller.
    """
    ctx = ssl.create_default_context()
    for path in _iter_ca_file_candidates():
        if not path or not os.path.isfile(path):
            continue
        try:
            ctx.load_verify_locations(cafile=path)
            return ctx
        except OSError:
            continue
    # Fall back to default context (may still work on Windows cert store / macOS)
    return ctx


# Module-level context reused across requests (CA paths do not change at runtime).
_SSL_CONTEXT: ssl.SSLContext | None = None


def _ssl_context() -> ssl.SSLContext:
    global _SSL_CONTEXT
    if _SSL_CONTEXT is None:
        _SSL_CONTEXT = build_ssl_context()
    return _SSL_CONTEXT


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


def _ssl_help_message(url: str, reason: object) -> str:
    reason_text = str(reason)
    if "CERTIFICATE_VERIFY_FAILED" in reason_text or "certificate verify failed" in reason_text.lower():
        return (
            f"URL error for {url}: {reason}\n"
            "TLS certificate verification failed. On Linux install system CA certificates:\n"
            "  Arch:            sudo pacman -S ca-certificates\n"
            "  Debian/Ubuntu:   sudo apt-get install ca-certificates\n"
            "  Fedora/RHEL:     sudo dnf install ca-certificates\n"
            "Then retry. You can also point Mira at a bundle explicitly:\n"
            "  export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt"
        )
    return f"URL error for {url}: {reason}"


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
        with urllib.request.urlopen(
            req,
            timeout=timeout + read_timeout,
            context=_ssl_context(),
        ) as resp:
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
        raise NetworkError(_ssl_help_message(url, e.reason)) from e
    except socket.timeout as e:
        raise NetworkError(f"Timeout fetching {url}") from e
    except ssl.SSLError as e:
        raise NetworkError(_ssl_help_message(url, e)) from e
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
