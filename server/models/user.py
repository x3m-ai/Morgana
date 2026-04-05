"""User model - Morgana platform user.

Supports:
  - Local (break glass) accounts with bcrypt password
  - OAuth2 accounts (Google, GitHub, Microsoft)
  - Enterprise OIDC SSO accounts

Roles: admin | contributor | reader
Auth providers: local | google | github | microsoft | oidc
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, Text
from database import Base

# --- Constants ---
BREAK_GLASS_EMAIL          = "admin@admin.com"
DEFAULT_BREAK_GLASS_PASSWORD = "admin"

ROLES          = frozenset({"admin", "contributor", "reader"})
AUTH_PROVIDERS = frozenset({"local", "google", "github", "microsoft", "oidc"})


class User(Base):
    """
    Morgana platform user.

    role:             admin | contributor | reader
    auth_provider:    local | google | github | microsoft | oidc
    provider_user_id: opaque ID returned by the OAuth/OIDC provider
    is_enabled:       False = cannot log in (break glass can never be disabled)
    workspaces:       JSON array of TagWorkspace IDs, or ["__ALL__"] for unrestricted access
    password_hash:    only set for local (break glass) accounts; None for OAuth users
    """
    __tablename__ = "users"

    id               = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name             = Column(String, nullable=False)
    email            = Column(String, unique=True, nullable=False, index=True)
    aka              = Column(String)

    # Auth
    password_hash    = Column(String, nullable=True)   # local accounts only
    role             = Column(String, default="contributor", nullable=False)    # admin | contributor | reader
    auth_provider    = Column(String, default="local",       nullable=False)    # local | google | github | microsoft | oidc
    provider_user_id = Column(String, index=True)                              # opaque ID from external provider

    # State
    is_enabled       = Column(Boolean, default=True,  nullable=False)

    # Visibility scope: JSON array of workspace IDs or ["__ALL__"]
    workspaces       = Column(Text, default='["__ALL__"]')

    # Token flows (local accounts only)
    activation_token   = Column(String, index=True)
    activation_expires = Column(DateTime)
    reset_token        = Column(String, index=True)
    reset_expires      = Column(DateTime)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime)

    # ------------------------------------------------------------------
    @property
    def is_break_glass(self) -> bool:
        return self.email.lower() == BREAK_GLASS_EMAIL

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def to_dict(self, include_sensitive: bool = False) -> dict:
        d = {
            "id":               self.id,
            "name":             self.name,
            "email":            self.email,
            "aka":              self.aka,
            "role":             self.role,
            "auth_provider":    self.auth_provider,
            "provider_user_id": self.provider_user_id,
            "is_enabled":       self.is_enabled,
            "is_break_glass":   self.is_break_glass,
            "workspaces":       self.workspaces or '["__ALL__"]',
            "created_at":       self.created_at.isoformat() if self.created_at else None,
            "updated_at":       self.updated_at.isoformat() if self.updated_at else None,
            "last_login":       self.last_login.isoformat() if self.last_login else None,
        }
        if include_sensitive:
            d["activation_token"] = self.activation_token
        return d
