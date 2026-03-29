"""
Atomic Red Team YAML loader.
Parses atomics/ directory and imports scripts into the Morgana database.
"""

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Optional

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


class AtomicLoader:
    def __init__(self, atomics_path: str):
        self.atomics_path = Path(atomics_path)

    def load_all(self) -> int:
        """Load all Atomic YAML files into the database. Returns count of imported scripts."""
        from database import SessionLocal
        from models.script import Script

        db = SessionLocal()
        total = 0

        try:
            yaml_files = list(self.atomics_path.rglob("T*.yaml"))
            log.info("[ATOMIC] Found %d YAML files in %s", len(yaml_files), self.atomics_path)

            for yaml_file in yaml_files:
                try:
                    count = self._load_file(db, yaml_file)
                    total += count
                except Exception as e:
                    log.warning("[ATOMIC] Failed to load %s: %s", yaml_file.name, str(e))

            db.commit()
            log.info("[ATOMIC] Loaded %d scripts total", total)
            return total

        except Exception as e:
            log.error("[ATOMIC] Load failed: %s", str(e))
            db.rollback()
            return 0
        finally:
            db.close()

    def _load_file(self, db, yaml_file: Path) -> int:
        from models.script import Script

        with open(yaml_file, "r", encoding="utf-8", errors="replace") as f:
            data = yaml.safe_load(f)

        if not data or not isinstance(data, dict):
            return 0

        attack_technique = data.get("attack_technique", "")
        tactic = ""
        if data.get("attack_tactic"):
            tactic = data["attack_tactic"]
        elif data.get("attack_tactics"):
            tactics = data["attack_tactics"]
            tactic = tactics[0] if tactics else ""

        atomic_tests = data.get("atomic_tests", [])
        if not atomic_tests:
            return 0

        count = 0
        for test in atomic_tests:
            try:
                script = self._parse_test(test, attack_technique, tactic)
                if script is None:
                    continue

                # Skip if already imported
                existing = db.query(Script).filter(Script.atomic_id == script.atomic_id).first()
                if existing:
                    continue

                db.add(script)
                count += 1
            except Exception as e:
                log.debug("[ATOMIC] Skipped test in %s: %s", yaml_file.name, str(e))

        return count

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
