"""CampaignExecution model - records a single run of a Campaign."""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, ForeignKey
from database import Base


class CampaignExecution(Base):
    __tablename__ = "campaign_executions"

    id             = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    campaign_id    = Column(String, ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True)
    campaign_name  = Column(String, nullable=False)
    agent_id       = Column(String, ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    agent_paw      = Column(String)
    agent_hostname = Column(String)
    state          = Column(String, default="running")  # running | completed | failed | partial
    flow_snapshot  = Column(Text)
    step_logs      = Column(Text, default="[]")          # JSON array of step results
    started_at     = Column(DateTime, default=datetime.utcnow)
    finished_at    = Column(DateTime)
    error          = Column(Text)
