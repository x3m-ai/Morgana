"""Job model - internal dispatch record created when a Test is queued for an Agent."""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Text, DateTime, ForeignKey
from database import Base


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    test_id = Column(String, ForeignKey("tests.id"), nullable=False)
    agent_id = Column(String, ForeignKey("agents.id"), nullable=False, index=True)
    script_id = Column(String, ForeignKey("scripts.id"), nullable=False)
    step_order = Column(Integer, default=1)
    # Payload sent to agent
    executor = Column(String, nullable=False)
    command = Column(Text, nullable=False)
    cleanup_command = Column(Text)
    input_args = Column(Text)         # Resolved JSON after applying overrides
    download_url = Column(Text)
    timeout_seconds = Column(Integer, default=300)
    # Lifecycle
    status = Column(String, default="pending", index=True)  # pending|dispatched|completed|failed
    dispatched_at = Column(DateTime)
    completed_at = Column(DateTime)
    # Security
    signature = Column(Text)          # HMAC-SHA256 of job payload
