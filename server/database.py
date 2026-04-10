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
    from models import script, chain, chain_execution, agent, test, campaign, campaign_execution, job, tag, api_key, user  # noqa: F401
    Base.metadata.create_all(bind=engine)
    _migrate()
    _seed()


def _seed():
    """Ensure system records exist (idempotent)."""
    _seed_adhoc_script()
    _seed_break_glass()


def _seed_adhoc_script():
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


def _seed_break_glass():
    """
    Ensure admin@admin.com break glass account exists.
    - Created with default password 'admin' (bcrypt).
    - Role: admin, provider: local, is_enabled: True.
    - Never disabled and always shown first in user lists.
    """
    import bcrypt as _bc
    from models.user import User, BREAK_GLASS_EMAIL, DEFAULT_BREAK_GLASS_PASSWORD

    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == BREAK_GLASS_EMAIL).first()
        if not existing:
            pw_hash = _bc.hashpw(DEFAULT_BREAK_GLASS_PASSWORD.encode(), _bc.gensalt(rounds=12)).decode()
            bg = User(
                name          = "Break Glass Admin",
                email         = BREAK_GLASS_EMAIL,
                password_hash = pw_hash,
                role          = "admin",
                auth_provider = "local",
                is_enabled    = True,
                workspaces    = '["__ALL__"]',
            )
            db.add(bg)
            db.commit()
            print(f"[SEED] Break glass account created: {BREAK_GLASS_EMAIL}")
    except Exception as exc:
        db.rollback()
        print(f"[WARN] Seed break glass: {exc}")
    finally:
        db.close()


def _migrate():
    """Add new nullable columns to existing tables (idempotent)."""
    migrations = [
        # Existing
        ("agents",    "alias",            "TEXT"),
        ("chains",    "flow_json",        "TEXT"),
        ("chains",    "agent_paw",        "TEXT"),
        ("campaigns", "flow_json",        "TEXT"),
        ("campaigns", "agent_paw",        "TEXT"),
        ("campaigns", "updated_at",       "TEXT"),
        # User table: new auth/role/visibility columns
        ("users",     "role",             "TEXT DEFAULT 'contributor'"),
        ("users",     "auth_provider",    "TEXT DEFAULT 'local'"),
        ("users",     "provider_user_id", "TEXT"),
        ("users",     "is_enabled",       "INTEGER DEFAULT 1"),
        ("users",     "workspaces",       "TEXT DEFAULT '[\"__ALL__\"]'"),
        ("users",     "updated_at",       "TEXT"),        # tests: denormalized script name for historical accuracy
        ("tests",     "script_name",      "TEXT"),        # password_hash was NOT NULL in old schema; SQLite doesn't allow ALTER COLUMN;
        # new rows created by ORM will have it as NULL (fine for OAuth accounts)
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
