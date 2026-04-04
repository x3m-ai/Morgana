"""Tag system - full typed tagging engine for Morgana."""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, Boolean, UniqueConstraint, Index
from database import Base

TAG_TYPES = frozenset({"flag", "string", "number", "boolean", "enum", "list", "json", "date"})
ENTITY_TYPES = frozenset({"agent", "script", "chain", "campaign", "user", "test"})


class TagDefinition(Base):
    """
    Typed, namespaced tag definition.

    key+value:  env=prod   -> key="env",   value="prod"
    key only:   critical   -> key="critical", value=None
    namespace:  logical grouping  (replaces old group_name)
    tag_type:   flag | string | number | boolean | enum | list | json | date
    scope:      JSON array  e.g. '["all"]' or '["agent","script"]'
    """
    __tablename__ = "tag_definitions"

    id               = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    label            = Column(String, nullable=False, index=True)
    key              = Column(String, nullable=False, index=True)
    value            = Column(String, nullable=True)
    namespace        = Column(String, nullable=False, default="general", index=True)
    tag_type         = Column(String, nullable=False, default="flag")
    description      = Column(Text)
    color            = Column(String, default="#667eea")
    icon             = Column(String)
    scope            = Column(Text, default='["all"]')
    allowed_values   = Column(Text)
    default_value    = Column(String)
    is_system        = Column(Boolean, default=False)
    is_filterable    = Column(Boolean, default=True)
    is_assignable    = Column(Boolean, default=True)
    is_runtime_param = Column(Boolean, default=False)
    is_inheritable   = Column(Boolean, default=False)
    capabilities     = Column(Text, default="{}")
    created_at       = Column(DateTime, default=datetime.utcnow)
    updated_at       = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("key", "value", "namespace", name="uq_tagdef_key_value_ns"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id, "label": self.label, "key": self.key, "value": self.value,
            "namespace": self.namespace, "tag_type": self.tag_type,
            "description": self.description, "color": self.color, "icon": self.icon,
            "scope": self.scope, "allowed_values": self.allowed_values,
            "default_value": self.default_value, "is_system": self.is_system,
            "is_filterable": self.is_filterable, "is_assignable": self.is_assignable,
            "is_runtime_param": self.is_runtime_param, "is_inheritable": self.is_inheritable,
            "capabilities": self.capabilities,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class TagAssignment(Base):
    """Assignment of a tag to an entity (many-to-many with optional value override)."""
    __tablename__ = "tag_assignments"

    id             = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tag_id         = Column(String, nullable=False, index=True)
    entity_type    = Column(String, nullable=False, index=True)
    entity_id      = Column(String, nullable=False, index=True)
    value_override = Column(String)
    assigned_at    = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("tag_id", "entity_type", "entity_id", name="uq_tag_assignment"),
        Index("ix_tag_assign_entity", "entity_type", "entity_id"),
    )


class TagWorkspace(Base):
    """Named workspace: saved tag selector expression applied globally in the UI."""
    __tablename__ = "tag_workspaces"

    id            = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name          = Column(String, nullable=False, unique=True)
    description   = Column(Text)
    selector_expr = Column(Text, nullable=False)
    is_active     = Column(Boolean, default=False)
    created_at    = Column(DateTime, default=datetime.utcnow)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "description": self.description,
            "selector_expr": self.selector_expr, "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
