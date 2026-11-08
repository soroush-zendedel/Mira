"""Post-apply functional verification for configured mirrors."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from mira.utils.network import fetch_url
from mira.exceptions import NetworkError


# Patterns that mean the mirror / network path is not usable
_FAIL_PATTERNS = re.compile(
    r"(NameResolutionError|getaddrinfo failed|Connection refused|Connection reset|"
    r"SSLError|CERTIFICATE_VERIFY_FAILED|ReadTimeout|ConnectTimeout|"
    r"Max retries exceeded|Failed to establish|Network is unreachable|"
    r"Temporary failure in name resolution|No route to host|"
    r"Could not resolve host|ProxyError|HTTPError 5\d\d)",
    re.IGNORECASE,
)

_RETRY_WARNING = re.compile(r"Retrying \(Retry\(total=", re.IGNORECASE)


def _run(cmd: list[str], *, timeout: float, env: dict[str, str] | None = None) -> tuple[int, str]:
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            check=False,
        )
        out = (p.stdout or "") + "\n" + (p.stderr or "")
        return p.returncode, out
    except subprocess.TimeoutExpired as e:
        out = ""
        if e.stdout:
            out += e.stdout if isinstance(e.stdout, str) else e.stdout.decode("utf-8", "replace")
        if e.stderr:
            out += e.stderr if isinstance(e.stderr, str) else e.stderr.decode("utf-8", "replace")
        return 124, out + "\nTIMEOUT"
    except OSError as e:
        return 127, str(e)


def _looks_like_network_failure(text: str, code: int) -> bool:
    if code == 124:
        return True
    if _FAIL_PATTERNS.search(text):
        return True
    if _RETRY_WARNING.search(text) and code != 0:
        return True
    return code != 0 and ("http" in text.lower() or "connection" in text.lower() or "resolve" in text.lower())


def verify_pypi(mirror: dict[str, Any], *, timeout: float = 90.0) -> dict[str, Any]:
    """
    Apply is assumed done. Run a real pip metadata fetch / upgrade-pip style probe.
    Prefer a dry network operation first (pip index versions pip) then optional upgrade.
    """
    url = mirror.get("url", "")
    host = urlparse(url).hostname or ""

    env = os.environ.copy()
    # Ensure pip sees user config; do not force global index via env (conf already set)
    # Use a short probe: download pip metadata only (no install) when possible.
    py = sys.executable

    # 1) pip index versions pip  (pip 21.2+) — pure metadata, uses index-url
    code, out = _run(
        [py, "-m", "pip", "index", "versions", "pip"],
        timeout=min(45.0, timeout),
        env=env,
    )
    if code == 0 and not _looks_like_network_failure(out, code):
        return {"ok": True, "method": "pip index versions pip", "detail": out.strip()[-300:]}

    # Some pip versions lack `pip index`; fall back to download wheel metadata
    if "No such command" in out or "unknown command" in out.lower() or code == 2:
        with tempfile.TemporaryDirectory(prefix="mira-pip-") as td:
            code2, out2 = _run(
                [
                    py, "-m", "pip", "download",
                    "pip",
                    "-d", td,
                    "--no-deps",
                    "--disable-pip-version-check",
                ],
                timeout=timeout,
                env=env,
            )
            if code2 == 0 and not _looks_like_network_failure(out2, code2):
                return {"ok": True, "method": "pip download pip", "detail": out2.strip()[-300:]}
            return {
                "ok": False,
                "method": "pip download pip",
                "detail": out2.strip()[-500:],
                "error": "pip download failed",
            }

    # `pip index` existed but failed
    if _looks_like_network_failure(out, code):
        return {
            "ok": False,
            "method": "pip index versions pip",
            "detail": out.strip()[-500:],
            "error": "network/index failure",
        }

    # Non-network failure: try download once more
    with tempfile.TemporaryDirectory(prefix="mira-pip-") as td:
        code3, out3 = _run(
            [
                py, "-m", "pip", "download",
                "pip",
                "-d", td,
                "--no-deps",
                "--disable-pip-version-check",
            ],
            timeout=timeout,
            env=env,
        )
        if code3 == 0 and not _looks_like_network_failure(out3, code3):
            return {"ok": True, "method": "pip download pip", "detail": out3.strip()[-300:]}
        return {
            "ok": False,
            "method": "pip download pip",
            "detail": (out + "\n" + out3).strip()[-500:],
            "error": "verification failed",
        }


def verify_debian(mirror: dict[str, Any], *, timeout: float = 30.0) -> dict[str, Any]:
    """Fetch Debian InRelease / Release from the mirror (no root required)."""
    base = mirror.get("url", "").rstrip("/")
    # Common paths
    candidates = [
        base + "/dists/stable/InRelease",
        base + "/dists/bookworm/InRelease",
        base + "/dists/jammy/InRelease",
        base + "/dists/noble/InRelease",
        base + "/dists/stable/Release",
    ]
    last_err = "no candidate URL worked"
    for probe in candidates:
        try:
            status, headers, body, latency = fetch_url(probe, timeout=timeout, max_size=256 * 1024)
            if 200 <= status < 400 and body:
                text = body[:200].decode("utf-8", "replace")
                if "Origin:" in text or "Suite:" in text or "Components:" in text or "Hash:" in text or len(body) > 64:
                    return {
                        "ok": True,
                        "method": f"GET {probe}",
                        "detail": f"HTTP {status} in {latency}ms",
                    }
            last_err = f"HTTP {status} for {probe}"
        except NetworkError as e:
            last_err = str(e)
            continue
    return {"ok": False, "method": "debian InRelease", "detail": last_err, "error": last_err}


def verify_docker(mirror: dict[str, Any], *, timeout: float = 25.0) -> dict[str, Any]:
    """Hit registry v2 endpoint or mirror base URL."""
    base = mirror.get("url", "").rstrip("/")
    probes = [
        base + "/v2/",
        base + "/v2",
        base,
    ]
    last_err = "no probe succeeded"
    for probe in probes:
        try:
            status, headers, body, latency = fetch_url(probe, timeout=timeout, max_size=64 * 1024)
            # Registry may return 200 or 401 Unauthorized for /v2/
            if status in (200, 401, 403) or (200 <= status < 500):
                docker_header = headers.get("Docker-Distribution-Api-Version") or headers.get(
                    "docker-distribution-api-version"
                )
                if status in (200, 401) or docker_header or status < 500:
                    return {
                        "ok": True,
                        "method": f"GET {probe}",
                        "detail": f"HTTP {status} in {latency}ms",
                    }
            last_err = f"HTTP {status} for {probe}"
        except NetworkError as e:
            last_err = str(e)
            continue
    return {"ok": False, "method": "docker registry probe", "detail": last_err, "error": last_err}


def verify_npm(mirror: dict[str, Any], *, timeout: float = 20.0) -> dict[str, Any]:
    """Fetch public package metadata from the selected npm registry."""
    probe = mirror.get("url", "").rstrip("/") + "/express"
    try:
        status, _, body, latency = fetch_url(probe, timeout=timeout, max_size=1024 * 1024)
        import json

        data = json.loads(body.decode("utf-8"))
        ok = (
            200 <= status < 300
            and isinstance(data, dict)
            and data.get("name") == "express"
            and isinstance(data.get("versions"), dict)
            and bool(data["versions"])
        )
        detail = f"HTTP {status} in {latency}ms" if ok else f"Unexpected npm metadata (HTTP {status})"
        return {"ok": ok, "method": f"GET {probe}", "detail": detail, **({} if ok else {"error": detail})}
    except (NetworkError, ValueError, UnicodeDecodeError) as e:
        return {"ok": False, "method": f"GET {probe}", "detail": str(e), "error": str(e)}


def verify_provider(provider_name: str, mirror: dict[str, Any]) -> dict[str, Any]:
    if provider_name == "pypi":
        return verify_pypi(mirror)
    if provider_name == "debian":
        return verify_debian(mirror)
    if provider_name == "docker":
        return verify_docker(mirror)
    if provider_name == "npm":
        return verify_npm(mirror)
    return {"ok": False, "error": f"no verifier for {provider_name}"}
