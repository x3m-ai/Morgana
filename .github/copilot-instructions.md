# Morgana - Agent Project Guide

> **Version:** 0.2.0 | **April 2026** | **Publisher:** X3M.AI Ltd (UK) | Author: Nino Crudele
> **Repo:** `x3m-ai/Morgana` (private)

---

## CRITICAL CONSTRAINTS

1. **NEVER commit or push** — Do NOT run `git commit` or `git push` unless the user explicitly asks for it. No exceptions.
2. **NO EMOJI in code** — No emoji in `.py`, `.go`, `.js`, `.html` files. Use `[START]`, `[SUCCESS]`, `[ERROR]` tags. Reason: UTF-8 corruption breaks automation.
3. **Merlino integration layer is FROZEN** — The Merlino side of the Caldera/Morgana integration must not change. See Merlino copilot-instructions for details.
4. **commit_history folder is MANDATORY** — Every time the user asks to commit and push, you MUST create a Markdown file in `commit_history/` BEFORE committing. The filename format is `YYYYMMDD_<short-hash>_<slug>.md` where `<short-hash>` is the hash of the most recent existing commit (7 chars) and `<slug>` is a short kebab-case description. The file must contain: date, commit hash(es), full description of every change made (files modified, root causes, fixes, test results). Include the commit_history file in the same commit. No exceptions.

---

## WHAT IS MORGANA

Morgana is the X3M.AI Red Team execution platform, replacing Caldera. Windows-native, lightweight, zero dependencies, tightly integrated with Merlino and Atomic Red Team.

## TECH STACK

| Layer | Technology |
|-------|------------|
| Server | Python 3.12 + FastAPI + SQLAlchemy + SQLite, port 8888 |
| Agent | Go 1.22 - single binary, NT Service (Windows) / systemd (Linux) |
| Script library | Red Canary Atomic Red Team (YAML, git submodule at `atomics/`) |
| UI | Vanilla HTML5/JS/CSS3 dark theme, no framework |
| Build | PyInstaller (server EXE) + Go build (agent EXE) |

## DOMAIN MODEL

| Morgana term | Meaning | Caldera equivalent |
|---|---|---|
| **Script** | Atomic execution unit | Ability |
| **Chain** | Ordered sequence of scripts | Adversary |
| **Test** | Single execution instance | Operation |
| **Campaign** | Named exercise grouping multiple Tests | (new concept) |
| **Agent** | OS Service on a target machine | Agent |
| **Job** | Internal dispatch record (server -> agent) | Task |

## QUICK START

```powershell
.\Start-Morgana.ps1           # Start (or restart)
.\Start-Morgana.ps1 -NoWindow # Background mode
```

Web UI: `http://localhost:8888/ui/`
