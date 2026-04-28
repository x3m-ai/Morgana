"""
Morgana Server - Configuration
All settings loaded from environment variables with sensible defaults.
"""

import os
import sys
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).parent

# When running as a PyInstaller frozen EXE, BASE_DIR resolves inside _MEIPASS (a
# temporary extraction folder that changes every run). To keep persistent data
# (certs, DB, logs) stable across restarts we use a well-known data directory
# instead. The env vars always take priority, so the installer / NSSM config can
# still override individual paths.
_FROZEN = getattr(sys, "frozen", False)
_DATA_DIR: Path = Path("C:/ProgramData/Morgana") if _FROZEN else BASE_DIR.parent

# Directory that contains the running server EXE (frozen) or the build/ output (dev).
# Agent binaries are placed next to the server EXE by the installer.
_APP_DIR: Path = Path(sys.executable).parent if _FROZEN else BASE_DIR.parent / "build"

# Path to persisted auto-generated master key
_MASTER_KEY_FILE = _DATA_DIR / "data" / "master.key"


def _get_or_generate_master_key() -> str:
    """
    Return the master API key.
    Priority:
      1. MORGANA_API_KEY environment variable (explicit override, e.g. NSSM config)
      2. Persisted key in server/data/master.key (auto-generated on first run)
    The key is NEVER a known default. On first run a random key is generated,
    saved to master.key and printed prominently in the server log at startup.
    """
    from_env = os.getenv("MORGANA_API_KEY", "")
    if from_env:
        return from_env

    if _MASTER_KEY_FILE.exists():
        stored = _MASTER_KEY_FILE.read_text().strip()
        if stored:
            return stored

    # First run: generate a cryptographically random key
    key = "mrg_" + secrets.token_hex(32)
    _MASTER_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    _MASTER_KEY_FILE.write_text(key)
    return key


class Settings:
    version: str = "0.2.6"

    # Server
    host: str = os.getenv("MORGANA_HOST", "0.0.0.0")
    port: int = int(os.getenv("MORGANA_PORT", "8888"))
    debug: bool = os.getenv("MORGANA_DEBUG", "false").lower() == "true"
    api_key: str = _get_or_generate_master_key()

    # CORS - allow Merlino (Excel Add-in) and local UI
    cors_origins: list = [
        "http://localhost:3000",
        "https://localhost:3000",
        "http://localhost:8888",
        "https://localhost:8888",
        "https://merlino-addin.x3m.ai",  # production Excel add-in (CF Pages)
        "null",  # file:// origins (Excel Desktop add-in)
    ]

    # TLS - always HTTPS. Override cert paths via env vars if needed.
    # Self-signed certs are auto-generated at startup if not found.
    ssl_certfile: str = os.getenv("MORGANA_CERT", str(_DATA_DIR / "certs" / "server.crt"))
    ssl_keyfile: str = os.getenv("MORGANA_KEY",  str(_DATA_DIR / "certs" / "server.key"))

    # Database
    db_path: str = os.getenv("MORGANA_DB", str(_DATA_DIR / "db" / "morgana.db"))

    # Data directory (exposed so other modules can derive subdirectories)
    data_dir: str = os.getenv("MORGANA_DATA_DIR", str(_DATA_DIR))

    # Atomic Red Team
    atomic_path: str = os.getenv("MORGANA_ATOMICS", str(_DATA_DIR / "atomics" / "atomics"))

    # Agent defaults
    default_beacon_interval: int = int(os.getenv("MORGANA_BEACON_INTERVAL", "5"))
    max_output_bytes: int = int(os.getenv("MORGANA_MAX_OUTPUT", str(100 * 1024)))  # 100KB

    # Agent binaries (served by /download/* endpoints)
    # Frozen: next to morgana-server.exe in C:\Program Files\Morgana Server\
    # Dev:    build/morgana-agent.exe (Go output)
    agent_binary_win: str   = os.getenv("MORGANA_AGENT_WIN",   str(_APP_DIR / "morgana-agent.exe"))
    agent_binary_linux: str = os.getenv("MORGANA_AGENT_LINUX", str(_APP_DIR / "morgana-agent"))

    # Logging
    log_file: str = os.getenv("MORGANA_LOG", str(_DATA_DIR / "logs" / "server.log"))

    # Security
    hmac_secret: str = os.getenv("MORGANA_HMAC_SECRET", "change-this-in-production-please")
    token_expire_days: int = int(os.getenv("MORGANA_TOKEN_EXPIRE_DAYS", "365"))
    secret_key: str = os.getenv("MORGANA_SECRET_KEY", "morgana-jwt-secret-change-in-production")
    jwt_expire_hours: int = int(os.getenv("MORGANA_JWT_EXPIRE_HOURS", "24"))

    # OAuth2 - Google
    oauth_google_client_id:     str = os.getenv("MORGANA_GOOGLE_CLIENT_ID", "")
    oauth_google_client_secret: str = os.getenv("MORGANA_GOOGLE_CLIENT_SECRET", "")

    # OAuth2 - GitHub
    oauth_github_client_id:     str = os.getenv("MORGANA_GITHUB_CLIENT_ID", "")
    oauth_github_client_secret: str = os.getenv("MORGANA_GITHUB_CLIENT_SECRET", "")

    # OAuth2 - Microsoft (Azure AD)
    oauth_microsoft_client_id:     str = os.getenv("MORGANA_MICROSOFT_CLIENT_ID", "")
    oauth_microsoft_client_secret: str = os.getenv("MORGANA_MICROSOFT_CLIENT_SECRET", "")
    oauth_microsoft_tenant:        str = os.getenv("MORGANA_MICROSOFT_TENANT", "common")

    # Enterprise OIDC SSO
    oidc_client_id:     str = os.getenv("MORGANA_OIDC_CLIENT_ID", "")
    oidc_client_secret: str = os.getenv("MORGANA_OIDC_CLIENT_SECRET", "")
    oidc_issuer_url:    str = os.getenv("MORGANA_OIDC_ISSUER", "")  # e.g. https://accounts.google.com or https://login.microsoftonline.com/{tenant}/v2.0

    # Public base URL for OAuth redirect URIs (auto-detects from request if empty)
    oauth_public_url: str = os.getenv("MORGANA_PUBLIC_URL", "")


settings = Settings()

# Ensure required directories exist
Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
Path(settings.log_file).parent.mkdir(parents=True, exist_ok=True)
