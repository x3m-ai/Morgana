"""
Atomic Red Team YAML loader.
Parses atomics/ directory and imports scripts into the Morgana database.

Behavior:
- load_all()   : on each boot, upserts all scripts (insert new, update changed, skip identical)
                 Fast-path: if no YAML file has changed since last run, skips all parsing.
- reload_all() : full wipe of atomic-red-team scripts then re-import (use after submodule update)
"""

import json
import logging
import uuid
from pathlib import Path
from typing import Optional, Tuple

import yaml

log = logging.getLogger("morgana.core.atomic_loader")

EXECUTOR_MAP = {
    "powershell": "powershell",
    "command_prompt": "cmd",
    "sh": "bash",
    "bash": "bash",
    "python": "python",
    "manual": "manual",
}

PLATFORM_MAP = {
    "windows": "windows",
    "linux": "linux",
    "macos": "macos",
    "darwin": "macos",
}

# Fields compared for change detection during upsert
_UPSERT_FIELDS = ("name", "command", "cleanup_command", "description", "tactic", "executor", "platform", "input_args")


class AtomicLoader:
    def __init__(self, atomics_path: str):
        self.atomics_path = Path(atomics_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_all(self) -> dict:
        """
        Boot-time loader. Upserts all Atomic scripts.
        Fast-path: if the max mtime across all YAML files is unchanged since the
        last successful run (stored in a stamp file), skip parsing entirely and
        return immediately so the server starts in seconds instead of minutes.
        Returns {"loaded": int, "updated": int, "skipped": int, "errors": int}
        """
        stamp_file = self.atomics_path.parent.parent / "server" / "db" / ".atomics_mtime_stamp"
        yaml_files = list(self.atomics_path.rglob("T*.yaml"))
        if yaml_files:
            max_mtime = max(f.stat().st_mtime for f in yaml_files)
            try:
                if stamp_file.exists():
                    stored = float(stamp_file.read_text().strip())
                    if stored >= max_mtime:
                        log.info("[ATOMIC] No changes since last load — skipping YAML parsing (fast-path)")
                        return {"loaded": 0, "updated": 0, "skipped": len(yaml_files), "errors": 0}
            except Exception:
                pass  # any read/parse error: fall through to full import
        else:
            max_mtime = None

        result = self._run_import(wipe_first=False)

        # Write stamp only on success (no errors or partial failures indicate bad state)
        if max_mtime is not None and result.get("errors", 0) == 0:
            try:
                stamp_file.parent.mkdir(parents=True, exist_ok=True)
                stamp_file.write_text(str(max_mtime))
            except Exception:
                pass

        return result

    def reload_all(self) -> dict:
        """
        Full reload: deletes all atomic-red-team scripts then re-imports from disk.
        Use this after `git submodule update` to pick up all YAML changes.
        Returns {"loaded": int, "updated": int, "skipped": int, "errors": int}
        """
        return self._run_import(wipe_first=True)

    # ------------------------------------------------------------------
    # Internal implementation
    # ------------------------------------------------------------------

    def _build_tactic_map(self) -> dict:
        """Parses Indexes/*.yaml to build {TCODE: tactic_name} mapping."""
        tactic_map = {}
        index_dir = self.atomics_path / "Indexes"
        if not index_dir.exists():
            log.warning("[ATOMIC] Indexes dir not found at %s", index_dir)
            return tactic_map
        for idx_file in index_dir.glob("*.yaml"):
            try:
                with open(idx_file, "r", encoding="utf-8", errors="replace") as f:
                    data = yaml.safe_load(f)
                if not data or not isinstance(data, dict):
                    continue
                for tactic_name, techniques in data.items():
                    if not isinstance(techniques, dict):
                        continue
                    for tcode in techniques.keys():
                        tactic_map[tcode.upper()] = tactic_name
            except Exception as e:
                log.warning("[ATOMIC] Failed to parse index %s: %s", idx_file.name, str(e))
        log.info("[ATOMIC] Tactic map built: %d entries", len(tactic_map))
        return tactic_map

    def fix_tactics(self) -> int:
        """One-time update: populate tactic field for all scripts with empty tactic.

        Fast-path: if no scripts with an empty tactic exist, returns 0 immediately.
        """
        from database import SessionLocal
        from models.script import Script

        db = SessionLocal()
        try:
            # Quick count check before building the full tactic map
            missing = db.query(Script.id).filter(Script.tactic == "").limit(1).first()
            if missing is None:
                return 0
        finally:
            db.close()
        tactic_map = self._build_tactic_map()
        if not tactic_map:
            return 0
        db = SessionLocal()
        try:
            scripts = db.query(Script).filter(Script.tactic == "").all()
            updated = 0
            for s in scripts:
                tcode = (s.tcode or "").upper()
                tactic = tactic_map.get(tcode, "")
                if not tactic and "." in tcode:
                    tactic = tactic_map.get(tcode.split(".")[0], "")
                if tactic:
                    s.tactic = tactic
                    updated += 1
            db.commit()
            log.info("[ATOMIC] fix_tactics: updated %d scripts", updated)
            return updated
        except Exception as e:
            log.error("[ATOMIC] fix_tactics failed: %s", str(e))
            db.rollback()
            return 0
        finally:
            db.close()

    def _run_import(self, wipe_first: bool) -> dict:
        from database import SessionLocal
        from models.script import Script

        db = SessionLocal()
        stats = {"loaded": 0, "updated": 0, "skipped": 0, "errors": 0}

        tactic_map = self._build_tactic_map()

        try:
            if wipe_first:
                deleted = db.query(Script).filter(Script.source == "atomic-red-team").delete()
                db.commit()
                log.info("[ATOMIC] Wiped %d existing atomic scripts for full reload", deleted)

            yaml_files = list(self.atomics_path.rglob("T*.yaml"))
            log.info("[ATOMIC] Found %d YAML files in %s", len(yaml_files), self.atomics_path)

            for yaml_file in yaml_files:
                try:
                    new, updated, skipped = self._load_file(db, yaml_file, tactic_map, upsert=not wipe_first)
                    stats["loaded"] += new
                    stats["updated"] += updated
                    stats["skipped"] += skipped
                except Exception as e:
                    stats["errors"] += 1
                    log.warning("[ATOMIC] Failed to load %s: %s", yaml_file.name, str(e))

            db.commit()
            log.info(
                "[ATOMIC] Done — loaded=%d updated=%d skipped=%d errors=%d",
                stats["loaded"], stats["updated"], stats["skipped"], stats["errors"],
            )
            return stats

        except Exception as e:
            log.error("[ATOMIC] Import failed: %s", str(e))
            db.rollback()
            return stats
        finally:
            db.close()

    def _load_file(self, db, yaml_file: Path, tactic_map: dict, upsert: bool) -> Tuple[int, int, int]:
        """Returns (new_count, updated_count, skipped_count)."""
        from models.script import Script

        with open(yaml_file, "r", encoding="utf-8", errors="replace") as f:
            data = yaml.safe_load(f)

        if not data or not isinstance(data, dict):
            return 0, 0, 0

        attack_technique = data.get("attack_technique", "")
        tcode_upper = attack_technique.upper()
        tactic = tactic_map.get(tcode_upper, "")
        if not tactic and "." in tcode_upper:
            tactic = tactic_map.get(tcode_upper.split(".")[0], "")

        atomic_tests = data.get("atomic_tests", [])
        if not atomic_tests:
            return 0, 0, 0

        new_count = updated_count = skipped_count = 0

        for test in atomic_tests:
            try:
                parsed = self._parse_test(test, attack_technique, tactic)
                if parsed is None:
                    skipped_count += 1
                    continue

                if not upsert:
                    # wipe_first=True path: just insert everything
                    db.add(parsed)
                    new_count += 1
                    continue

                existing = db.query(Script).filter(Script.atomic_id == parsed.atomic_id).first()
                if existing is None:
                    db.add(parsed)
                    new_count += 1
                else:
                    # Upsert: update only if any key field changed
                    changed = False
                    for field in _UPSERT_FIELDS:
                        if getattr(existing, field) != getattr(parsed, field):
                            setattr(existing, field, getattr(parsed, field))
                            changed = True
                    if changed:
                        updated_count += 1
                    else:
                        skipped_count += 1

            except Exception as e:
                log.debug("[ATOMIC] Skipped test in %s: %s", yaml_file.name, str(e))
                skipped_count += 1

        return new_count, updated_count, skipped_count

    def _parse_test(self, test: dict, tcode: str, tactic: str) -> Optional[object]:
        from models.script import Script

        test_name = test.get("name", "")
        test_guid = test.get("auto_generated_guid", str(uuid.uuid4()))
        description = test.get("description", "")
        supported_platforms = test.get("supported_platforms", ["windows"])

        executor_block = test.get("executor", {})
        executor_name_raw = executor_block.get("name", "manual") if executor_block else "manual"
        executor_name = EXECUTOR_MAP.get(executor_name_raw, "manual")

        command = ""
        if executor_block:
            command = executor_block.get("command", "") or executor_block.get("steps", "") or ""
            command = command.strip() if command else ""

        cleanup_command = ""
        if executor_block:
            cleanup_command = executor_block.get("cleanup_command", "") or ""
            cleanup_command = cleanup_command.strip()

        # Parse input arguments
        input_args_raw = test.get("input_arguments", {})
        input_args = {}
        if input_args_raw and isinstance(input_args_raw, dict):
            for arg_name, arg_data in input_args_raw.items():
                if isinstance(arg_data, dict):
                    input_args[arg_name] = {
                        "type": arg_data.get("type", "string"),
                        "default": arg_data.get("default", ""),
                        "description": arg_data.get("description", ""),
                    }

        # Map platform
        platform = "all"
        if supported_platforms:
            platforms_mapped = [PLATFORM_MAP.get(p.lower(), p.lower()) for p in supported_platforms]
            if len(platforms_mapped) == 1:
                platform = platforms_mapped[0]
            else:
                platform = ",".join(platforms_mapped)

        if not command and executor_name != "manual":
            return None

        return Script(
            id=str(uuid.uuid4()),
            name=test_name,
            description=description,
            tcode=tcode,
            tactic=tactic,
            executor=executor_name,
            command=command[:10000] if command else "",
            cleanup_command=cleanup_command[:5000] if cleanup_command else None,
            input_args=json.dumps(input_args) if input_args else None,
            source="atomic-red-team",
            atomic_id=test_guid,
            platform=platform,
        )
