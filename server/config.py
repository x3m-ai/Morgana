"""
Morgana Server - Configuration
All settings loaded from environment variables with sensible defaults.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).parent


class Settings:
    version: str = "0.2.0"

    # Server
    host: str = os.getenv("MORGANA_HOST", "0.0.0.0")
    port: int = int(os.getenv("MORGANA_PORT", "8888"))
    debug: bool = os.getenv("MORGANA_DEBUG", "false").lower() == "true"
    api_key: str = os.getenv("MORGANA_API_KEY", "MORGANA_ADMIN_KEY")

    # CORS - allow Merlino (Excel Add-in) and local UI
    cors_origins: list = [
        "https://localhost:3000",
        "https://localhost:8888",
        "null",  # file:// origins (Excel Desktop add-in)
    ]

    # TLS - disabled by default for local dev; set MORGANA_SSL=true + provide certs for production
    ssl_enabled: bool = os.getenv("MORGANA_SSL", "false").lower() == "true"
    ssl_certfile: str = os.getenv("MORGANA_CERT", str(BASE_DIR / "certs" / "server.crt"))
    ssl_keyfile: str = os.getenv("MORGANA_KEY", str(BASE_DIR / "certs" / "server.key"))

    # Database
    db_path: str = os.getenv("MORGANA_DB", str(BASE_DIR / "db" / "morgana.db"))

    # Atomic Red Team
    atomic_path: str = os.getenv("MORGANA_ATOMICS", str(BASE_DIR.parent / "atomics" / "atomics"))

    # Agent defaults
    default_beacon_interval: int = int(os.getenv("MORGANA_BEACON_INTERVAL", "5"))
    max_output_bytes: int = int(os.getenv("MORGANA_MAX_OUTPUT", str(100 * 1024)))  # 100KB

    # Agent binaries (served by /download/* endpoints)
    agent_binary_win: str   = os.getenv("MORGANA_AGENT_WIN",   str(BASE_DIR.parent / "build" / "morgana-agent.exe"))
    agent_binary_linux: str = os.getenv("MORGANA_AGENT_LINUX", str(BASE_DIR.parent / "build" / "morgana-agent"))

    # Logging
    log_file: str = os.getenv("MORGANA_LOG", str(BASE_DIR / "logs" / "server.log"))

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
