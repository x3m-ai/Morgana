"""Test model - an execution instance of a Script or Chain against an Agent."""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Text, DateTime, ForeignKey
from database import Base


class Test(Base):
    __tablename__ = "tests"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    # What was run
    chain_id = Column(String, ForeignKey("chains.id"), nullable=True)
    script_id = Column(String, ForeignKey("scripts.id"), nullable=True)
    script_name = Column(String)  # denormalized -- survives script deletion/reload
    tcode = Column(String)
    # Where / by whom
    agent_id = Column(String, ForeignKey("agents.id"), nullable=True, index=True)
    campaign_id = Column(String, ForeignKey("campaigns.id"), nullable=True)
    # Merlino integration fields
    operation_id = Column(String)
    adversary_id = Column(String)
    operation_name = Column(String)
    adversary_name = Column(String)
    assigned = Column(String)
    group_name = Column(String)
    # Lifecycle
    state = Column(String, default="pending", index=True)
    # Results
    exit_code = Column(Integer)
    stdout = Column(Text)
    stderr = Column(Text)
    duration_ms = Column(Integer)
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
