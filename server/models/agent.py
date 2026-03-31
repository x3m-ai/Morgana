"""Agent model - registered Morgana agent (NT Service / systemd daemon)."""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Boolean, DateTime
from database import Base


class Agent(Base):
    __tablename__ = "agents"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    paw = Column(String, unique=True, nullable=False, index=True)
    hostname = Column(String, nullable=False)
    ip_address = Column(String)
    platform = Column(String, nullable=False)   # windows|linux|macos
    architecture = Column(String)               # amd64|arm64|x86
    os_version = Column(String)
    agent_version = Column(String)
    status = Column(String, default="offline")  # online|offline|idle|busy
    last_seen = Column(DateTime)
    beacon_interval = Column(Integer, default=30)
    work_dir = Column(String)
    token_hash = Column(String)                 # HMAC of agent_token (never plaintext)
    enrolled_at = Column(DateTime, default=datetime.utcnow)
    enrolled_by = Column(String)                # deploy_token hash used
    tags = Column(String)                       # JSON array
    alias = Column(String, nullable=True)       # operator-assigned human name
