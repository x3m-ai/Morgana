"""Tag model - labeling system shared across all Morgana entities."""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, UniqueConstraint
from database import Base


class Tag(Base):
    """A named label with group, description and scope.

    scope: which entities can use this tag.
    Values: 'all' | 'agent' | 'script' | 'chain' | 'test' | 'campaign'
    """
    __tablename__ = "tags"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False, index=True)
    group_name = Column(String, nullable=False, default="general")  # logical grouping
    description = Column(Text)
    scope = Column(String, default="all")   # all|agent|script|chain|test|campaign
    color = Column(String, default="#667eea")  # CSS hex color for badge
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("name", "group_name", name="uq_tag_name_group"),)


class EntityTag(Base):
    """Many-to-many: any entity type <-> tags."""
    __tablename__ = "entity_tags"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    entity_type = Column(String, nullable=False, index=True)  # agent|script|chain|test|campaign
    entity_id = Column(String, nullable=False, index=True)
    tag_id = Column(String, nullable=False, index=True)

    __table_args__ = (UniqueConstraint("entity_type", "entity_id", "tag_id", name="uq_entity_tag"),)
