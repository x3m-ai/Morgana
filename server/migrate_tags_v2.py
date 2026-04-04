"""
migrate_tags_v2.py - Migrate Morgana DB to Tag System v2.

What this does:
1. Creates new tables: tag_definitions, tag_assignments, tag_workspaces, users
2. Migrates old 'tags' records -> tag_definitions (name->label, name->key, group_name->namespace)
3. Migrates old 'entity_tags' records -> tag_assignments
4. Adds new columns to scripts (target_agent_paw, target_tag_selector, tag_params)
5. Adds new columns to chains (target_tag_selector, tag_params)
6. Adds new columns to campaigns (target_tag_selector, tag_params)

Safe to run multiple times (idempotent).
"""
import sys
import sqlite3
import uuid
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent / "db" / "morgana.db"

def run():
    print(f"[START] Migrating DB: {DB_PATH}")
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("PRAGMA journal_mode=WAL")

    now = datetime.utcnow().isoformat()

    # ── 1. Create new tables ─────────────────────────────────────────────────
    c.executescript("""
    CREATE TABLE IF NOT EXISTS tag_definitions (
        id               TEXT PRIMARY KEY,
        label            TEXT NOT NULL,
        key              TEXT NOT NULL,
        value            TEXT,
        namespace        TEXT NOT NULL DEFAULT 'general',
        tag_type         TEXT NOT NULL DEFAULT 'flag',
        description      TEXT,
        color            TEXT DEFAULT '#667eea',
        icon             TEXT,
        scope            TEXT DEFAULT '["all"]',
        allowed_values   TEXT,
        default_value    TEXT,
        is_system        INTEGER DEFAULT 0,
        is_filterable    INTEGER DEFAULT 1,
        is_assignable    INTEGER DEFAULT 1,
        is_runtime_param INTEGER DEFAULT 0,
        is_inheritable   INTEGER DEFAULT 0,
        capabilities     TEXT DEFAULT '{}',
        created_at       TEXT,
        updated_at       TEXT
    );

    CREATE TABLE IF NOT EXISTS tag_assignments (
        id             TEXT PRIMARY KEY,
        tag_id         TEXT NOT NULL,
        entity_type    TEXT NOT NULL,
        entity_id      TEXT NOT NULL,
        value_override TEXT,
        assigned_at    TEXT,
        UNIQUE(tag_id, entity_type, entity_id)
    );
    CREATE INDEX IF NOT EXISTS ix_tag_assign_entity ON tag_assignments(entity_type, entity_id);

    CREATE TABLE IF NOT EXISTS tag_workspaces (
        id            TEXT PRIMARY KEY,
        name          TEXT NOT NULL UNIQUE,
        description   TEXT,
        selector_expr TEXT NOT NULL,
        is_active     INTEGER DEFAULT 0,
        created_at    TEXT,
        updated_at    TEXT
    );

    CREATE TABLE IF NOT EXISTS users (
        id                 TEXT PRIMARY KEY,
        name               TEXT NOT NULL,
        email              TEXT UNIQUE NOT NULL,
        aka                TEXT,
        password_hash      TEXT NOT NULL,
        is_active          INTEGER DEFAULT 0,
        is_admin           INTEGER DEFAULT 0,
        activation_token   TEXT,
        activation_expires TEXT,
        reset_token        TEXT,
        reset_expires      TEXT,
        tags               TEXT DEFAULT '[]',
        created_at         TEXT,
        last_login         TEXT
    );
    CREATE INDEX IF NOT EXISTS ix_users_email ON users(email);
    CREATE INDEX IF NOT EXISTS ix_users_activation ON users(activation_token);
    """)
    print("[OK] New tables created/verified")

    # ── 2. Migrate old tags -> tag_definitions ───────────────────────────────
    try:
        old_tags = c.execute("SELECT * FROM tags").fetchall()
        migrated = 0
        for row in old_tags:
            # Check if already migrated by ID
            exists = c.execute(
                "SELECT id FROM tag_definitions WHERE id=?", (row["id"],)
            ).fetchone()
            if exists:
                continue
            c.execute("""
                INSERT INTO tag_definitions
                  (id, label, key, value, namespace, tag_type, description, color, scope,
                   is_system, is_filterable, is_assignable, is_runtime_param, is_inheritable,
                   capabilities, created_at, updated_at)
                VALUES (?,?,?,NULL,?,?,?,?,'["all"]',0,1,1,0,0,'{}',?,?)
            """, (
                row["id"],
                row["name"],           # label
                row["name"].lower().replace(" ", "_"),  # key
                (row["group_name"] or "general").lower(),  # namespace
                "flag",                # tag_type
                row["description"] or "",
                row["color"] or "#667eea",
                row["created_at"] or now,
                now,
            ))
            migrated += 1
        conn.commit()
        print(f"[OK] Migrated {migrated} records from tags -> tag_definitions")
    except sqlite3.OperationalError as e:
        if "no such table" in str(e):
            print(f"[SKIP] Old 'tags' table not found: {e}")
        else:
            print(f"[WARN] tags migration error: {e}")

    # ── 3. Migrate old entity_tags -> tag_assignments ────────────────────────
    try:
        old_et = c.execute("SELECT * FROM entity_tags").fetchall()
        migrated = 0
        for row in old_et:
            exists = c.execute(
                "SELECT id FROM tag_assignments WHERE id=?", (row["id"],)
            ).fetchone()
            if exists:
                continue
            c.execute("""
                INSERT OR IGNORE INTO tag_assignments
                  (id, tag_id, entity_type, entity_id, value_override, assigned_at)
                VALUES (?,?,?,?,NULL,?)
            """, (
                row["id"],
                row["tag_id"],
                row["entity_type"],
                row["entity_id"],
                now,
            ))
            migrated += 1
        conn.commit()
        print(f"[OK] Migrated {migrated} records from entity_tags -> tag_assignments")
    except sqlite3.OperationalError as e:
        if "no such table" in str(e):
            print(f"[SKIP] Old 'entity_tags' table not found: {e}")
        else:
            print(f"[WARN] entity_tags migration error: {e}")

    # ── 4. Add new columns to existing tables ────────────────────────────────
    def add_column_if_missing(table, col, col_def):
        rows = c.execute(f"PRAGMA table_info({table})").fetchall()
        cols = [r["name"] for r in rows]
        if col not in cols:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}")
            conn.commit()
            print(f"[OK] Added {table}.{col}")
        else:
            print(f"[SKIP] {table}.{col} already exists")

    add_column_if_missing("scripts", "target_agent_paw", "TEXT")
    add_column_if_missing("scripts", "target_tag_selector", "TEXT")
    add_column_if_missing("scripts", "tag_params", "TEXT DEFAULT '{}'")
    add_column_if_missing("chains",  "target_tag_selector", "TEXT")
    add_column_if_missing("chains",  "tag_params", "TEXT DEFAULT '{}'")
    add_column_if_missing("campaigns", "target_tag_selector", "TEXT")
    add_column_if_missing("campaigns", "tag_params", "TEXT DEFAULT '{}'")

    conn.close()
    print("[SUCCESS] Migration complete")

if __name__ == "__main__":
    run()
