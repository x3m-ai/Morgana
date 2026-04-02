"""Chain model - ordered sequence of scripts forming an attack path."""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Boolean, Text, DateTime, ForeignKey
from database import Base


class Chain(Base):
    __tablename__ = "chains"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    description = Column(Text)
    objective = Column(Text)
    tcode_coverage = Column(Text)   # Comma-separated TCodes
    author = Column(String)
    tags = Column(String)           # JSON array
    flow_json  = Column(Text, default='{"nodes":[]}')   # Visual flow definition
    agent_paw  = Column(String)        # Default agent to execute this chain
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ChainStep(Base):
    __tablename__ = "chain_steps"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    chain_id = Column(String, ForeignKey("chains.id", ondelete="CASCADE"), nullable=False)
    script_id = Column(String, ForeignKey("scripts.id"), nullable=False)
    step_order = Column(Integer, nullable=False)
    input_overrides = Column(Text)      # JSON overrides for this step
    stop_on_failure = Column(Boolean, default=True)
    delay_seconds = Column(Integer, default=0)
