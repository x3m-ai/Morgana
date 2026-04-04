"""Script model - atomic unit of execution."""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime
from database import Base


class Script(Base):
    __tablename__ = "scripts"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    description = Column(Text)
    tcode = Column(String, nullable=False, index=True)
    tactic = Column(String)
    executor = Column(String, nullable=False)  # powershell|cmd|bash|python|manual
    command = Column(Text, nullable=False)
    cleanup_command = Column(Text)
    input_args = Column(Text)          # JSON: {arg_name: {type, default, description}}
    download_url = Column(Text)
    source = Column(String, default="morgana")  # atomic-red-team|morgana|system
    atomic_id = Column(String)         # Original Atomic test GUID
    platform = Column(String, default="all")  # windows|linux|macos|all
    target_agent_paw    = Column(String)        # default execution agent
    target_tag_selector = Column(Text)          # JSON/DSL selector: resolve agents at runtime
    tag_params          = Column(Text, default="{}")  # JSON: {PARAM_KEY: {type, value, description}}
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
