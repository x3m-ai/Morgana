"""
Morgana - ApiKey model

Stores hashed API keys. The plaintext key is only returned at creation time
and never stored. Authentication checks the SHA-256 hash.

Key format: mrg_<32 hex bytes>  (68 chars total)
Stored:     SHA-256 hash of full key
Displayed:  mrg_xxxxxx... (first 12 chars + ...)
"""

from datetime import datetime, timezone

from sqlalchemy import Column, String, DateTime

from database import Base


class ApiKey(Base):
    __tablename__ = "api_keys"

    id         = Column(String, primary_key=True)   # uuid4
    name       = Column(String, nullable=False)      # user-visible label
    key_hash   = Column(String, nullable=False, unique=True)  # sha256 hex
    key_prefix = Column(String, nullable=False)      # first 12 chars for display
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
