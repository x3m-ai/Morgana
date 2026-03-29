"""Campaign model - named grouping of Tests for a specific exercise."""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Table
from database import Base

campaign_tests = Table(
    "campaign_tests",
    Base.metadata,
    Column("campaign_id", String, ForeignKey("campaigns.id", ondelete="CASCADE")),
    Column("test_id", String, ForeignKey("tests.id", ondelete="CASCADE")),
)


class Campaign(Base):
    __tablename__ = "campaigns"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    description = Column(Text)
    objective = Column(Text)
    status = Column(String, default="planning")  # planning|active|completed|archived
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
