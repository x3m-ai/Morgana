"""Campaign model - named sequence of Chains forming a multi-stage exercise."""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime
from database import Base


class Campaign(Base):
    __tablename__ = "campaigns"

    id          = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name        = Column(String, nullable=False)
    description = Column(Text)
    flow_json   = Column(Text, default='{"nodes":[]}')
    agent_paw   = Column(String)
    # Legacy columns kept for backward compat (not used by new logic)
    status       = Column(String, default="planning")
    objective    = Column(Text)
    created_at   = Column(DateTime, default=datetime.utcnow)
    updated_at   = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
