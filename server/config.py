"""
Morgana Server - Configuration
All settings loaded from environment variables with sensible defaults.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).parent


class Settings:
    version: str = "0.1.0"

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
    default_beacon_interval: int = int(os.getenv("MORGANA_BEACON_INTERVAL", "30"))
    max_output_bytes: int = int(os.getenv("MORGANA_MAX_OUTPUT", str(100 * 1024)))  # 100KB

    # Logging
    log_file: str = os.getenv("MORGANA_LOG", str(BASE_DIR / "logs" / "server.log"))

    # Security
    hmac_secret: str = os.getenv("MORGANA_HMAC_SECRET", "change-this-in-production-please")
    token_expire_days: int = int(os.getenv("MORGANA_TOKEN_EXPIRE_DAYS", "365"))


settings = Settings()

# Ensure required directories exist
Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
Path(settings.log_file).parent.mkdir(parents=True, exist_ok=True)
