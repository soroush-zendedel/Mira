"""Application constants for Mira."""

from pathlib import Path

APP_NAME = "mira"
APP_VERSION = "1.0.29"
APP_DESCRIPTION = "Universal Software Repository Mirror Manager"

# GitHub repository (official source)
GITHUB_OWNER = "soroush-zendedel"
GITHUB_REPO = "Mira"
GITHUB_RAW_BASE = f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/main"
GITHUB_API_BASE = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}"
GITHUB_RELEASES_URL = f"{GITHUB_API_BASE}/releases/latest"
MIRROR_MANIFEST_URL = f"{GITHUB_RAW_BASE}/mirrors/manifest.json"
# Single archive of the whole repo (used by `mira update` to fetch the mirrors/ tree at once)
MIRROR_ARCHIVE_URL = f"https://codeload.github.com/{GITHUB_OWNER}/{GITHUB_REPO}/zip/refs/heads/main"

# Schema
SCHEMA_VERSION = 1
DEFAULT_DATABASE_VERSION = "1.0.0"

# Timeouts and limits
DEFAULT_CONNECT_TIMEOUT = 5.0
DEFAULT_READ_TIMEOUT = 10.0
DEFAULT_MAX_WORKERS = 8
DEFAULT_HEALTH_CACHE_TTL = 900  # 15 minutes
DEFAULT_HISTORY_WINDOW = 86400  # 24 hours
MAX_RETRIES = 2

# Scoring weights (percentages)
SCORE_WEIGHTS = {
    "availability": 0.35,
    "validity": 0.30,
    "latency": 0.20,
    "stability": 0.10,
    "priority": 0.05,
}

# Latency scoring: best latency gets full score, worse get less
MAX_LATENCY_MS = 5000.0  # beyond this is considered very slow

# Providers
SUPPORTED_PROVIDERS = ("pypi", "npm", "debian", "docker", "pacman")

# Config paths (relative names)
CONFIG_DIR_NAME = "mira"
CONFIG_FILE_NAME = "config.json"
DATABASE_DIR_NAME = "database"
CACHE_DIR_NAME = "cache"
BACKUPS_DIR_NAME = "backups"

# Default user config
DEFAULT_CONFIG = {
    "schema_version": 1,
    "countries": ["*"],
    "timeout": DEFAULT_CONNECT_TIMEOUT,
    "read_timeout": DEFAULT_READ_TIMEOUT,
    "max_workers": DEFAULT_MAX_WORKERS,
    "strategy": "balanced",  # balanced | fastest | reliability
    "health_cache_ttl": DEFAULT_HEALTH_CACHE_TTL,
    "prefer_countries": [],
    "path_offer_declined": False,
    "path_configured": False,
}

# Terminal
USE_COLOR_DEFAULT = True
