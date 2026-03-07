#!/bin/bash
# ============================================
# DMX Controller - Automated Installer
# For Raspberry Pi (Pi 4 & Pi 5, Bookworm)
# ============================================
set -e

INSTALL_DIR="/opt/dmx"
SERVICE_NAME="dmx"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUN_USER="${SUDO_USER:-$(whoami)}"

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
    err "This script must be run as root.  Try:  sudo ./install.sh"
    exit 1
fi

if [ "$RUN_USER" = "root" ]; then
    err "Do not run as the root user directly.  Use:  sudo ./install.sh"
    err "(SUDO_USER must be set so the service runs as a non-root account)"
    exit 1
fi

echo ""
echo "========================================"
echo "  DMX Controller Installer"
echo "  DJPOWER H-IP20V Fog Machine"
echo "========================================"
echo ""
info "Install directory : ${INSTALL_DIR}"
info "Service user      : ${RUN_USER}"
info "Systemd unit      : ${SERVICE_FILE}"
echo ""

# ------------------------------------------
# 1. System packages
# ------------------------------------------
info "Updating package list..."
apt-get update -qq

info "Installing system dependencies..."
apt-get install -y -qq \
    python3 \
    python3-venv \
    python3-pip \
    python3-dev \
    libusb-1.0-0-dev \
    libgpiod-dev \
    curl \
    git > /dev/null 2>&1
ok "System packages installed"

# ------------------------------------------
# 2. Blacklist ftdi_sio kernel module
# ------------------------------------------
# The kernel's ftdi_sio driver claims FTDI USB devices before pyftdi can
# access them.  Blacklisting is required for the ENTTEC adapter to work.
MODPROBE_FILE="/etc/modprobe.d/ftdi-blacklist.conf"
if [ ! -f "$MODPROBE_FILE" ]; then
    info "Blacklisting ftdi_sio kernel module..."
    cat > "$MODPROBE_FILE" <<'BLACKLIST'
# Prevent the kernel ftdi_sio driver from claiming ENTTEC / FTDI devices
# so that pyftdi (userspace) can access them via libusb.
blacklist ftdi_sio
BLACKLIST
    ok "ftdi_sio blacklisted in ${MODPROBE_FILE}"
else
    ok "ftdi_sio blacklist already in place"
fi

# Unload ftdi_sio if currently loaded
if lsmod | grep -q ftdi_sio; then
    info "Unloading ftdi_sio kernel module..."
    rmmod ftdi_sio 2>/dev/null || warn "Could not unload ftdi_sio (may need a reboot)"
fi

# ------------------------------------------
# 3. FTDI udev rules (non-root USB access)
# ------------------------------------------
UDEV_RULES="/etc/udev/rules.d/99-ftdi-dmx.rules"
if [ ! -f "$UDEV_RULES" ]; then
    info "Creating FTDI udev rules..."
    cat > "$UDEV_RULES" <<'UDEV'
# ENTTEC Open DMX USB / FTDI devices — allow non-root access
SUBSYSTEM=="usb", ATTR{idVendor}=="0403", ATTR{idProduct}=="6001", MODE="0666", GROUP="plugdev"
SUBSYSTEM=="usb", ATTR{idVendor}=="0403", ATTR{idProduct}=="6014", MODE="0666", GROUP="plugdev"
UDEV
    udevadm control --reload-rules
    udevadm trigger
    ok "udev rules installed (unplug/replug the ENTTEC adapter)"
else
    ok "udev rules already exist"
fi

# Add user to plugdev group
if ! id -nG "$RUN_USER" | grep -qw plugdev; then
    usermod -aG plugdev "$RUN_USER"
    ok "Added ${RUN_USER} to plugdev group"
fi

# ------------------------------------------
# 4. Stop existing service (safe for reinstall)
# ------------------------------------------
if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
    info "Stopping existing ${SERVICE_NAME} service for upgrade..."
    systemctl stop "$SERVICE_NAME"
    ok "Existing service stopped"
fi

# ------------------------------------------
# 5. Copy application files
# ------------------------------------------
info "Installing application to ${INSTALL_DIR}..."
mkdir -p "$INSTALL_DIR"
cp -f "$SCRIPT_DIR"/app.py            "$INSTALL_DIR/"
cp -f "$SCRIPT_DIR"/index.html        "$INSTALL_DIR/"
cp -f "$SCRIPT_DIR"/start.sh          "$INSTALL_DIR/"
cp -f "$SCRIPT_DIR"/requirements.txt  "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/start.sh"
chown -R "$RUN_USER":"$RUN_USER" "$INSTALL_DIR"
ok "Application files copied"

# ------------------------------------------
# 5b. Persistent config directory
# ------------------------------------------
CONFIG_DIR="/var/lib/dmx"
info "Creating config directory at ${CONFIG_DIR}..."
mkdir -p "$CONFIG_DIR"
chown -R "$RUN_USER":"$RUN_USER" "$CONFIG_DIR"
if [ -f "${CONFIG_DIR}/config.json" ]; then
    ok "Config directory ready (existing config.json preserved)"
else
    ok "Config directory ready"
fi

# ------------------------------------------
# 5c. Environment file (config path)
# ------------------------------------------
ENV_DIR="/etc/dmx"
ENV_FILE="${ENV_DIR}/dmx.env"
info "Creating environment file at ${ENV_FILE}..."
mkdir -p "$ENV_DIR"
if [ ! -f "$ENV_FILE" ]; then
    cat > "$ENV_FILE" <<EOF
DMX_CONFIG_DIR=${CONFIG_DIR}
EOF
    chown root:"$RUN_USER" "$ENV_FILE"
    chmod 640 "$ENV_FILE"
    ok "Environment file created"
else
    ok "Environment file already exists"
fi

# ------------------------------------------
# 6. Python virtual environment & packages
# ------------------------------------------
info "Setting up Python virtual environment..."
sudo -u "$RUN_USER" python3 -m venv "$INSTALL_DIR/venv"

info "Installing Python dependencies..."
sudo -u "$RUN_USER" "$INSTALL_DIR/venv/bin/pip" install --upgrade pip -q
sudo -u "$RUN_USER" "$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt" -q
ok "Python dependencies installed"

# ------------------------------------------
# 7. Systemd service
# ------------------------------------------
info "Creating systemd service..."
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=DMX Controller - DJPOWER H-IP20V
After=network.target

[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${INSTALL_DIR}/venv/bin/gunicorn --workers 1 --threads 4 --bind 0.0.0.0:5000 app:app
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

# Give access to USB and GPIO
SupplementaryGroups=plugdev gpio

# Improve timing stability for DMX output
Nice=-10
CPUSchedulingPolicy=fifo
CPUSchedulingPriority=10
LimitRTPRIO=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
ok "Systemd service created and enabled"

# ------------------------------------------
# 8. Start the service
# ------------------------------------------
info "Starting DMX controller service..."
systemctl restart "$SERVICE_NAME"
sleep 3

if systemctl is-active --quiet "$SERVICE_NAME"; then
    ok "Service is running"
else
    warn "Service may not have started (ENTTEC adapter might not be plugged in)"
    warn "Check logs with:  sudo journalctl -u ${SERVICE_NAME} -f"
fi

# ------------------------------------------
# 9. Health check
# ------------------------------------------
info "Running health check..."
HEALTH_OK=false
for i in 1 2 3 4 5; do
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 3 --max-time 5 http://127.0.0.1:5000/api/health 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "503" ]; then
        # 200 = fully healthy, 503 = degraded (ENTTEC not plugged in) — both mean app is up
        HEALTH_OK=true
        break
    fi
    sleep 3
done

if [ "$HEALTH_OK" = true ]; then
    ok "Health check passed (HTTP ${HTTP_CODE})"
else
    warn "Health check did not respond (the service may still be starting)"
    warn "Check logs:  sudo journalctl -u ${SERVICE_NAME} -f"
fi

# ------------------------------------------
# Done
# ------------------------------------------
echo ""
echo "========================================"
echo -e "  ${GREEN}Installation complete!${NC}"
echo "========================================"
echo ""
echo "  Useful commands:"
echo "    sudo systemctl status  ${SERVICE_NAME}   # Check status"
echo "    sudo systemctl restart ${SERVICE_NAME}   # Restart"
echo "    sudo systemctl stop    ${SERVICE_NAME}   # Stop"
echo "    sudo journalctl -u ${SERVICE_NAME} -f    # View logs"
echo ""

# Detect IP for convenience
IP=$(hostname -I 2>/dev/null | awk '{print $1}')
if [ -n "$IP" ]; then
    echo -e "  Web interface: ${CYAN}http://${IP}:5000${NC}"
else
    echo "  Web interface: http://<your-pi-ip>:5000"
fi


echo ""
echo "  The service starts automatically on boot."
echo "  Plug in the ENTTEC Open DMX USB adapter and"
echo "  connect your DJPOWER H-IP20V fog machine."
echo ""
echo "  To uninstall:  sudo ./uninstall.sh"
echo ""
