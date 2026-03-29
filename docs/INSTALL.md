# Morgana Installation Guide

> **Version:** 1.0.0 | X3M.AI Ltd

---

## Requirements

| Component | Requirement |
|-----------|-------------|
| Server OS | Windows 10/11/Server 2019+, macOS 12+, Ubuntu 20.04+ |
| Python | 3.11+ (server dev) or use pre-built EXE |
| Agent OS | Windows 10/11/Server 2019+ or Linux (kernel 4.15+) |
| Network | Agent must reach server on TCP 8888 (configurable) |
| Antivirus | Exclusion needed on agent work directory (by design — Atomic tests trigger AV) |

---

## Quick Start (Development)

```bash
# 1. Clone the repo
git clone https://github.com/x3m-ai/Morgana.git
cd Morgana

# 2. Initialize Atomic Red Team submodule
git submodule update --init --recursive

# 3. Install server dependencies
cd server
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/macOS
pip install -r requirements.txt

# 4. Start the server
python main.py
# Server starts on https://localhost:8888
# Web UI at https://localhost:8888/ui/
```

---

## Production Deployment (Windows)

### Build server EXE
```powershell
cd build
python build-server.py
# Output: dist/morgana-server.exe (self-contained, ~50MB)
```

### Build agent EXE
```powershell
cd agent\build
.\build-windows.ps1
# Output: agent/bin/morgana-agent.exe (Windows amd64)
#         agent/bin/morgana-agent-linux (Linux amd64)
```

### Run as Windows Service
```powershell
# Install Morgana Server as an NT Service manually (or use NSSM):
nssm install MorganaServer "C:\Morgana\morgana-server.exe"
nssm set MorganaServer AppDirectory "C:\Morgana"
nssm set MorganaServer Start SERVICE_AUTO_START
nssm start MorganaServer
```

### Place agent binaries for download
Copy `morgana-agent.exe` and `morgana-agent-linux` to a folder served by Morgana:
```
Morgana\ui\download\morgana-agent.exe
Morgana\ui\download\morgana-agent-linux
```
The installer scripts download from `${ServerUrl}/download/morgana-agent.exe`.

---

## Agent Installation

### Windows (one-liner, run as Administrator)
```powershell
irm https://YOUR_SERVER:8888/ui/install.ps1 | iex
```
Or with parameters:
```powershell
.\install-agent-windows.ps1 -ServerUrl https://192.168.1.10:8888 -Token YOUR_API_KEY
```

### Linux (one-liner, run as root)
```bash
curl -fsSL https://YOUR_SERVER:8888/ui/install.sh | bash -s -- \
  --server https://192.168.1.10:8888 --token YOUR_API_KEY
```

---

## TLS Certificate

Morgana generates a self-signed certificate by default. For production:
1. Replace `server/certs/server.key` and `server/certs/server.crt` with a valid cert.
2. Or set `MORGANA_SSL=false` and put Morgana behind a reverse proxy (nginx/Caddy).

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MORGANA_HOST` | `0.0.0.0` | Bind address |
| `MORGANA_PORT` | `8888` | TCP port |
| `MORGANA_API_KEY` | `MORGANA_ADMIN_KEY` | **Change this** — used by Merlino + UI + deploy tokens |
| `MORGANA_SSL` | `true` | Enable HTTPS |
| `MORGANA_DB` | `db/morgana.db` | SQLite database path |
| `MORGANA_ATOMICS` | `../atomics` | Atomic Red Team submodule path |
| `MORGANA_HMAC_SECRET` | auto-generated | Job signing secret — set to a fixed value in prod |
| `MORGANA_DEBUG` | `false` | Enable FastAPI auto-reload |

---

## Antivirus Exclusions

Atomic Red Team tests **intentionally trigger antivirus**. Add exclusions for:
- Agent work directory: `C:\ProgramData\Morgana\agent\work\` (Windows)
- Agent work directory: `/opt/morgana/agent/work/` (Linux)

This is expected behavior — catching these triggers is the goal of Purple Teaming.

---

## Merlino Integration

See [docs/MERLINO_INTEGRATION.md](MERLINO_INTEGRATION.md) for step-by-step instructions.

TL;DR: In Merlino Settings, change the Caldera URL to `https://YOUR_MORGANA_SERVER:8888` and update the API key. No other changes needed.

---

## Upgrading

1. Stop the server: `Stop-Service MorganaServer` or `systemctl stop morgana-server`
2. Replace the binary / pull git changes
3. Re-run `pip install -r requirements.txt` if updating the server from source
4. Restart the server
5. The SQLite DB and config are preserved automatically.
