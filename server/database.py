"""
Morgana Server - Database setup (SQLAlchemy + SQLite)
"""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import NullPool
from config import settings

DATABASE_URL = f"sqlite:///{settings.db_path}"

# NullPool: each SessionLocal() opens its own connection and closes it on release.
# This is required for parallel threads (e.g. campaign parallel branch execution)
# because StaticPool shares a single connection across all threads, causing
# silent commit conflicts when multiple threads write concurrently.
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30},
    poolclass=NullPool,
)


# Enable WAL mode and foreign keys for SQLite
@event.listens_for(engine, "connect")
def set_sqlite_pragmas(dbapi_conn, _):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA synchronous=NORMAL")
    # busy_timeout: wait up to 10s for a write lock instead of failing immediately.
    # Critical for parallel branch execution where multiple threads write concurrently.
    cursor.execute("PRAGMA busy_timeout=10000")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_db():
    """Create all tables and apply lightweight migrations."""
    from models import script, chain, chain_execution, agent, test, campaign, campaign_execution, job, tag  # noqa: F401 - import to register models
    Base.metadata.create_all(bind=engine)
    _migrate()
    _seed()


def _seed():
    """Ensure system records exist (idempotent)."""
    from models.script import Script as ScriptModel
    db = SessionLocal()
    try:
        if not db.query(ScriptModel).filter(ScriptModel.id == "_adhoc").first():
            db.add(ScriptModel(
                id="_adhoc",
                name="_SYSTEM_ADHOC",
                tcode="_ADHOC",
                executor="cmd",
                command="",
                source="system",
                platform="all",
            ))
            db.commit()
    except Exception as exc:
        db.rollback()
        print(f"[WARN] Seed _adhoc: {exc}")
    finally:
        db.close()


def _migrate():
    """Add new nullable columns to existing tables (idempotent)."""
    migrations = [
        ("agents",    "alias",       "TEXT"),
        ("chains",    "flow_json",   "TEXT"),
        ("chains",    "agent_paw",   "TEXT"),
        ("campaigns", "flow_json",   "TEXT"),
        ("campaigns", "agent_paw",   "TEXT"),
        ("campaigns", "updated_at",  "TEXT"),
    ]
    with engine.connect() as conn:
        for table, col, col_type in migrations:
            try:
                result = conn.execute(__import__("sqlalchemy").text(f"PRAGMA table_info({table})"))
                existing = [row[1] for row in result.fetchall()]
                if col not in existing:
                    conn.execute(__import__("sqlalchemy").text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"))
                    conn.commit()
            except Exception as exc:
                print(f"[WARN] Migration {table}.{col}: {exc}")


def get_db():
    """FastAPI dependency - yields a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
