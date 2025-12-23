#!/bin/bash
###############################################################################
# Fix Signage Pi User Permissions
# Usage: sudo bash fix-user-permissions.sh
# 
# This script fixes installations where root was used instead of actual user
###############################################################################

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Detect actual user
if [ -n "$SUDO_USER" ]; then
    ACTUAL_USER="$SUDO_USER"
    ACTUAL_HOME=$(getent passwd "$SUDO_USER" | cut -d: -f6)
else
    echo -e "${RED}ERROR: This script must be run with sudo${NC}"
    exit 1
fi

SIGNAGE_HOME="${ACTUAL_HOME}/.signage"
APP_HOME="/opt/signage-pi"
VENV_PATH="/opt/signage-pi/venv"

echo -e "${BLUE}[INFO]${NC} Detected user: $ACTUAL_USER"
echo -e "${BLUE}[INFO]${NC} Home directory: $ACTUAL_HOME"
echo -e "${BLUE}[INFO]${NC} Signage directory: $SIGNAGE_HOME"
echo ""

# 1. Stop services
echo -e "${BLUE}[INFO]${NC} Stopping services..."
systemctl stop signage-dashboard.service 2>/dev/null || true
systemctl stop signage-web-player.service 2>/dev/null || true

# 2. Move data from /root/.signage if exists
if [ -d "/root/.signage" ] && [ ! -d "$SIGNAGE_HOME" ]; then
    echo -e "${BLUE}[INFO]${NC} Moving data from /root/.signage to $SIGNAGE_HOME..."
    mv /root/.signage "$SIGNAGE_HOME"
    chown -R "$ACTUAL_USER:$ACTUAL_USER" "$SIGNAGE_HOME"
elif [ -d "/root/.signage" ] && [ -d "$SIGNAGE_HOME" ]; then
    echo -e "${YELLOW}[WARN]${NC} Both /root/.signage and $SIGNAGE_HOME exist. Manual merge required."
    echo -e "${YELLOW}[WARN]${NC} Skipping data move. Old data remains at /root/.signage"
fi

# 3. Create directories if needed
echo -e "${BLUE}[INFO]${NC} Ensuring directories exist..."
mkdir -p "$SIGNAGE_HOME"/{content/videos,content/presentations,cache/slides,logs,commands}
chown -R "$ACTUAL_USER:$ACTUAL_USER" "$SIGNAGE_HOME"
chmod -R 755 "$SIGNAGE_HOME"

# 4. Update systemd services
echo -e "${BLUE}[INFO]${NC} Updating systemd services..."

if [ -f /etc/systemd/system/signage-dashboard.service ]; then
    sed -i "s|User=.*|User=$ACTUAL_USER|g" /etc/systemd/system/signage-dashboard.service
    sed -i "s|Group=.*|Group=$ACTUAL_USER|g" /etc/systemd/system/signage-dashboard.service
    sed -i "s|HOME=/.*|HOME=$ACTUAL_HOME|g" /etc/systemd/system/signage-dashboard.service
    sed -i "s|/home/[^/]*/\.signage|$SIGNAGE_HOME|g" /etc/systemd/system/signage-dashboard.service
    sed -i "s|/root/\.signage|$SIGNAGE_HOME|g" /etc/systemd/system/signage-dashboard.service
fi

if [ -f /etc/systemd/system/signage-web-player.service ]; then
    sed -i "s|User=.*|User=$ACTUAL_USER|g" /etc/systemd/system/signage-web-player.service
    sed -i "s|Group=.*|Group=$ACTUAL_USER|g" /etc/systemd/system/signage-web-player.service
    sed -i "s|HOME=/.*|HOME=$ACTUAL_HOME|g" /etc/systemd/system/signage-web-player.service
    sed -i "s|/home/[^/]*/\.signage|$SIGNAGE_HOME|g" /etc/systemd/system/signage-web-player.service
    sed -i "s|/root/\.signage|$SIGNAGE_HOME|g" /etc/systemd/system/signage-web-player.service
fi

# 5. Reload systemd
echo -e "${BLUE}[INFO]${NC} Reloading systemd daemon..."
systemctl daemon-reload

# 6. Start services
echo -e "${BLUE}[INFO]${NC} Starting services..."
systemctl start signage-dashboard.service
systemctl start signage-web-player.service
sleep 2

# 7. Check status
echo ""
echo -e "${GREEN}=== Service Status ===${NC}"
if systemctl is-active --quiet signage-dashboard.service; then
    echo -e "${GREEN}[✓]${NC} Dashboard service is running"
else
    echo -e "${RED}[✗]${NC} Dashboard service failed (check: sudo journalctl -u signage-dashboard -n 50)"
fi

if systemctl is-active --quiet signage-web-player.service; then
    echo -e "${GREEN}[✓]${NC} Web Player service is running"
else
    echo -e "${RED}[✗]${NC} Web Player service failed (check: sudo journalctl -u signage-web-player -n 50)"
fi

echo ""
PI_IP=$(hostname -I | awk '{print $1}')
echo -e "${GREEN}=== Access Points ===${NC}"
echo "Dashboard:   http://${PI_IP}:5000"
echo "Web Player:  http://${PI_IP}:8080"
echo ""
echo -e "${GREEN}[✓]${NC} Fix complete!"
