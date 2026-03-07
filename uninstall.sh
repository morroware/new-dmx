#!/bin/bash
# ============================================
# DMX Controller - Uninstaller
# Cleanly removes all installed components
# ============================================
set -e

SERVICE_NAME="dmx"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
INSTALL_DIR="/opt/dmx"
CONFIG_DIR="/var/lib/dmx"
ENV_DIR="/etc/dmx"
UDEV_RULES="/etc/udev/rules.d/99-ftdi-dmx.rules"
MODPROBE_FILE="/etc/modprobe.d/ftdi-blacklist.conf"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC}  $1"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
err()   { echo -e "${RED}[ERROR]${NC} $1"; }

# ------------------------------------------
# Pre-flight checks
# ------------------------------------------
if [ "$EUID" -ne 0 ]; then
    err "This script must be run as root.  Try:  sudo ./uninstall.sh"
    exit 1
fi

echo ""
echo "========================================"
echo "  DMX Controller Uninstaller"
echo "========================================"
echo ""
warn "This will remove the DMX controller service and application files."
echo ""
read -p "  Continue? [y/N] " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    info "Uninstall cancelled."
    exit 0
fi
echo ""

# ------------------------------------------
# 1. Stop and disable the systemd service
# ------------------------------------------
if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
    info "Stopping ${SERVICE_NAME} service..."
    systemctl stop "$SERVICE_NAME"
    ok "Service stopped"
fi

if systemctl is-enabled --quiet "$SERVICE_NAME" 2>/dev/null; then
    info "Disabling ${SERVICE_NAME} service..."
    systemctl disable "$SERVICE_NAME"
    ok "Service disabled"
fi

if [ -f "$SERVICE_FILE" ]; then
    info "Removing systemd unit file..."
    rm -f "$SERVICE_FILE"
    systemctl daemon-reload
    ok "Systemd unit removed"
fi

# ------------------------------------------
# 2. Remove application files
# ------------------------------------------
if [ -d "$INSTALL_DIR" ]; then
    info "Removing application directory ${INSTALL_DIR}..."
    rm -rf "$INSTALL_DIR"
    ok "Application files removed"
fi

# ------------------------------------------
# 3. Remove udev rules
# ------------------------------------------
if [ -f "$UDEV_RULES" ]; then
    info "Removing FTDI udev rules..."
    rm -f "$UDEV_RULES"
    udevadm control --reload-rules 2>/dev/null || true
    ok "udev rules removed"
fi

# ------------------------------------------
# 4. Remove ftdi_sio blacklist
# ------------------------------------------
if [ -f "$MODPROBE_FILE" ]; then
    info "Removing ftdi_sio kernel module blacklist..."
    rm -f "$MODPROBE_FILE"
    ok "ftdi_sio blacklist removed (module will load on next boot)"
fi

# ------------------------------------------
# 5. Optionally remove configuration and secrets
# ------------------------------------------
echo ""
HAS_CONFIG=false
if [ -d "$CONFIG_DIR" ] || [ -d "$ENV_DIR" ]; then
    HAS_CONFIG=true
fi

if [ "$HAS_CONFIG" = true ]; then
    warn "Saved configuration and API token still exist:"
    [ -d "$CONFIG_DIR" ] && echo "    ${CONFIG_DIR}  (scene config)"
    [ -d "$ENV_DIR" ]    && echo "    ${ENV_DIR}     (API token)"
    echo ""
    read -p "  Remove saved configuration and API token? [y/N] " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        [ -d "$CONFIG_DIR" ] && rm -rf "$CONFIG_DIR"
        [ -d "$ENV_DIR" ]    && rm -rf "$ENV_DIR"
        ok "Configuration and secrets removed"
    else
        info "Configuration preserved (reinstall will reuse it)"
    fi
fi

# ------------------------------------------
# Done
# ------------------------------------------
echo ""
echo "========================================"
echo -e "  ${GREEN}Uninstall complete!${NC}"
echo "========================================"
echo ""
echo "  The DMX controller has been removed."
echo "  System packages (python3, libusb, etc.) were left in place."
echo ""
