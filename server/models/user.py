"""User model - Morgana platform user with basic auth."""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, Text
from database import Base


class User(Base):
    """
    Morgana platform user.

    aka:    hacker handle / operator nickname
    is_active: set True after email activation
    is_admin:  can access admin-only endpoints
    """
    __tablename__ = "users"

    id                  = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name                = Column(String, nullable=False)
    email               = Column(String, unique=True, nullable=False, index=True)
    aka                 = Column(String)
    password_hash       = Column(String, nullable=False)
    is_active           = Column(Boolean, default=False)
    is_admin            = Column(Boolean, default=False)
    activation_token    = Column(String, index=True)
    activation_expires  = Column(DateTime)
    reset_token         = Column(String, index=True)
    reset_expires       = Column(DateTime)
    tags                = Column(Text, default="[]")   # JSON array of tag_ids
    created_at          = Column(DateTime, default=datetime.utcnow)
    last_login          = Column(DateTime)

    def to_dict(self, include_sensitive: bool = False) -> dict:
        d = {
            "id": self.id, "name": self.name, "email": self.email,
            "aka": self.aka, "is_active": self.is_active, "is_admin": self.is_admin,
            "tags": self.tags,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_login": self.last_login.isoformat() if self.last_login else None,
        }
        if include_sensitive:
            d["activation_token"] = self.activation_token
        return d
