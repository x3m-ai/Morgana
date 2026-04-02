"""ChainExecution model - records a single run of a Chain on an Agent."""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, ForeignKey
from database import Base


class ChainExecution(Base):
    __tablename__ = "chain_executions"

    id            = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    chain_id      = Column(String, ForeignKey("chains.id", ondelete="SET NULL"), nullable=True)
    chain_name    = Column(String, nullable=False)
    agent_id      = Column(String, ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    agent_paw     = Column(String)
    agent_hostname= Column(String)
    state         = Column(String, default="running")   # running | completed | failed
    flow_snapshot = Column(Text)                        # JSON copy of chain.flow_json at run time
    step_logs     = Column(Text, default="[]")          # JSON array of step results
    started_at    = Column(DateTime, default=datetime.utcnow)
    finished_at   = Column(DateTime)
    error         = Column(Text)
