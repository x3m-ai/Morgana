#!/bin/bash
# Morgana Agent Installer for Linux
# X3M.AI Red Team Platform
#
# Usage (from Morgana server web):
#   curl -fsSL https://SERVER:8888/ui/install.sh | bash -s -- --server https://SERVER:8888 --token TOKEN
#
# Or manually:
#   chmod +x install-agent-linux.sh
#   sudo ./install-agent-linux.sh --server https://192.168.1.10:8888 --token MYTOKEN

set -euo pipefail

MORGANA_SERVER=""
MORGANA_TOKEN=""
MORGANA_INTERVAL=30
INSTALL_DIR="/opt/morgana/agent"
WORK_DIR="/opt/morgana/agent/work"
BINARY_NAME="morgana-agent-linux"

# ─── Colors ──────────────────────────────────────────────────────────────────
RED="\e[31m"; GREEN="\e[32m"; CYAN="\e[36m"; RESET="\e[0m"; BOLD="\e[1m"

banner() {
  echo ""
  echo -e "${CYAN}${BOLD}  Morgana Agent Installer${RESET}"
  echo -e "${CYAN}  X3M.AI Red Team Platform${RESET}"
  echo ""
}

log_info()    { echo -e "${CYAN}[INFO]${RESET}    $*"; }
log_success() { echo -e "${GREEN}[SUCCESS]${RESET} $*"; }
log_error()   { echo -e "${RED}[ERROR]${RESET}   $*" >&2; }

# ─── Argument parsing ─────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --server)   MORGANA_SERVER="$2"; shift 2 ;;
    --token)    MORGANA_TOKEN="$2";  shift 2 ;;
    --interval) MORGANA_INTERVAL="$2"; shift 2 ;;
    --workdir)  WORK_DIR="$2"; shift 2 ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

# ─── Interactive prompts if not supplied ─────────────────────────────────────
if [[ -z "$MORGANA_SERVER" ]]; then
  read -rp "Enter Morgana server URL (e.g. https://192.168.1.10:8888): " MORGANA_SERVER
fi
if [[ -z "$MORGANA_TOKEN" ]]; then
  read -rsp "Enter deploy token: " MORGANA_TOKEN; echo ""
fi

# ─── Prerequisite checks ─────────────────────────────────────────────────────
banner

if [[ $EUID -ne 0 ]]; then
  log_error "This script must be run as root (or via sudo)."
  exit 1
fi

for cmd in curl systemctl; do
  if ! command -v "$cmd" &>/dev/null; then
    log_error "Required command not found: $cmd"
    exit 1
  fi
done

# ─── Create directories ───────────────────────────────────────────────────────
log_info "Creating installation directory: $INSTALL_DIR"
mkdir -p "$INSTALL_DIR" "$WORK_DIR"
chmod 700 "$INSTALL_DIR"

# ─── Download binary ──────────────────────────────────────────────────────────
DOWNLOAD_URL="${MORGANA_SERVER}/download/${BINARY_NAME}"
BINARY_PATH="${INSTALL_DIR}/morgana-agent"

log_info "Downloading agent from $DOWNLOAD_URL ..."
if ! curl -fsSL --insecure -o "$BINARY_PATH" "$DOWNLOAD_URL"; then
  log_error "Download failed. Place the binary manually at $BINARY_PATH"
  exit 1
fi
chmod +x "$BINARY_PATH"
log_success "Binary saved to $BINARY_PATH"

# ─── Install as systemd service ───────────────────────────────────────────────
log_info "Registering systemd service ..."
"$BINARY_PATH" install --server "$MORGANA_SERVER" --token "$MORGANA_TOKEN" --interval "$MORGANA_INTERVAL"

log_success "Morgana Agent installed and started."
echo ""
echo "  Config:  /etc/morgana/config.json"
echo "  Logs:    /var/log/morgana/"
echo "  Work:    $WORK_DIR"
echo ""
echo "Useful commands:"
echo "  systemctl status morgana-agent    -- Check service status"
echo "  journalctl -u morgana-agent -f    -- Follow logs"
echo "  $BINARY_PATH status               -- Full diagnostics"
echo "  $BINARY_PATH uninstall            -- Remove agent"
echo ""
