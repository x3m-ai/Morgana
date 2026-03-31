"""
Morgana Server - Database setup (SQLAlchemy + SQLite)
"""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool
from config import settings

DATABASE_URL = f"sqlite:///{settings.db_path}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


# Enable WAL mode and foreign keys for SQLite
@event.listens_for(engine, "connect")
def set_sqlite_pragmas(dbapi_conn, _):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_db():
    """Create all tables and apply lightweight migrations."""
    from models import script, chain, agent, test, campaign, job, tag  # noqa: F401 - import to register models
    Base.metadata.create_all(bind=engine)
    _migrate()


def _migrate():
    """Add new nullable columns to existing tables (idempotent)."""
    migrations = [
        ("agents", "alias", "TEXT"),
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
