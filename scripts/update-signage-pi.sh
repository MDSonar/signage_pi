#!/bin/bash
###############################################################################
# Signage Pi - Update/Redeploy Script
# Usage: sudo bash scripts/update-signage-pi.sh
# 
# This script updates an existing installation:
# - Pulls latest code from git (if in git repo)
# - Updates application files
# - Restarts services
# - Preserves data and configuration
###############################################################################

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
REPO_PATH="$(pwd)"
APP_HOME="/opt/signage-pi"
VENV_PATH="/opt/signage-pi/venv"

# Detect actual user
if [ -n "$SUDO_USER" ]; then
    ACTUAL_USER="$SUDO_USER"
    ACTUAL_HOME=$(getent passwd "$SUDO_USER" | cut -d: -f6)
else
    echo -e "${RED}[ERROR]${NC} This script must be run with sudo"
    exit 1
fi

SIGNAGE_HOME="${ACTUAL_HOME}/.signage"

echo -e "${BLUE}===========================================${NC}"
echo -e "${BLUE}Signage Pi - Update & Redeploy${NC}"
echo -e "${BLUE}===========================================${NC}"
echo -e "${BLUE}[INFO]${NC} User: $ACTUAL_USER"
echo -e "${BLUE}[INFO]${NC} Repo: $REPO_PATH"
echo -e "${BLUE}[INFO]${NC} Data: $SIGNAGE_HOME (preserved)"
echo ""

# 1. Pull latest code (if git repo)
if [ -d ".git" ]; then
    echo -e "${BLUE}[INFO]${NC} Step 1: Pulling latest code from git..."
    sudo -u "$ACTUAL_USER" git pull
    echo -e "${GREEN}[✓]${NC} Code updated"
else
    echo -e "${YELLOW}[WARN]${NC} Step 1: Not a git repository, skipping pull"
fi

# 2. Stop services
echo -e "${BLUE}[INFO]${NC} Step 2: Stopping services..."
systemctl stop signage-dashboard.service 2>/dev/null || true
systemctl stop signage-web-player.service 2>/dev/null || true
echo -e "${GREEN}[✓]${NC} Services stopped"

# 3. Update application code
echo -e "${BLUE}[INFO]${NC} Step 3: Updating application code..."
cp -f "$REPO_PATH"/*.py "$APP_HOME/" 2>/dev/null || true
cp -rf "$REPO_PATH"/templates "$APP_HOME/" 2>/dev/null || true
cp -f "$REPO_PATH"/requirements.txt "$APP_HOME/" 2>/dev/null || true
cp -f "$REPO_PATH"/start_*.sh "$APP_HOME/" 2>/dev/null || true
chmod +x "$APP_HOME"/start_*.sh 2>/dev/null || true
echo -e "${GREEN}[✓]${NC} Application code updated"

# 4. Update Python dependencies
echo -e "${BLUE}[INFO]${NC} Step 4: Updating Python dependencies..."
source "$VENV_PATH/bin/activate"
pip install --upgrade pip -q
pip install -r "$APP_HOME/requirements.txt" -q
deactivate
echo -e "${GREEN}[✓]${NC} Dependencies updated"

# 5. Update systemd services (in case they changed)
echo -e "${BLUE}[INFO]${NC} Step 5: Updating systemd services..."
if [ -f "$REPO_PATH/signage-dashboard.service" ]; then
    cp "$REPO_PATH/signage-dashboard.service" /etc/systemd/system/signage-dashboard.service
    
    # Apply user/path substitutions
    sed -i "s|User=pi|User=$ACTUAL_USER|g" /etc/systemd/system/signage-dashboard.service
    sed -i "s|Group=pi|Group=$ACTUAL_USER|g" /etc/systemd/system/signage-dashboard.service
    sed -i "s|/home/pi/.signage|$SIGNAGE_HOME|g" /etc/systemd/system/signage-dashboard.service
    sed -i "s|HOME=/home/pi|HOME=$ACTUAL_HOME|g" /etc/systemd/system/signage-dashboard.service
fi

if [ -f "$REPO_PATH/signage-web-player.service" ]; then
    cp "$REPO_PATH/signage-web-player.service" /etc/systemd/system/signage-web-player.service
    
    # Apply user/path substitutions
    sed -i "s|User=pi|User=$ACTUAL_USER|g" /etc/systemd/system/signage-web-player.service
    sed -i "s|Group=pi|Group=$ACTUAL_USER|g" /etc/systemd/system/signage-web-player.service
    sed -i "s|/home/pi/.signage|$SIGNAGE_HOME|g" /etc/systemd/system/signage-web-player.service
    sed -i "s|HOME=/home/pi|HOME=$ACTUAL_HOME|g" /etc/systemd/system/signage-web-player.service
fi

systemctl daemon-reload
echo -e "${GREEN}[✓]${NC} Services updated"

# 6. Start services
echo -e "${BLUE}[INFO]${NC} Step 6: Starting services..."
systemctl start signage-dashboard.service
systemctl start signage-web-player.service
sleep 2

# 7. Check status
echo ""
echo -e "${GREEN}===========================================${NC}"
if systemctl is-active --quiet signage-dashboard.service; then
    echo -e "${GREEN}[✓]${NC} Dashboard service is running"
else
    echo -e "${RED}[✗]${NC} Dashboard service failed"
    echo -e "${YELLOW}    Check logs: sudo journalctl -u signage-dashboard -n 50${NC}"
fi

if systemctl is-active --quiet signage-web-player.service; then
    echo -e "${GREEN}[✓]${NC} Web Player service is running"
else
    echo -e "${RED}[✗]${NC} Web Player service failed"
    echo -e "${YELLOW}    Check logs: sudo journalctl -u signage-web-player -n 50${NC}"
fi

PI_IP=$(hostname -I | awk '{print $1}')
echo ""
echo -e "${GREEN}=== Access Points ===${NC}"
echo "Dashboard:   http://${PI_IP}:5000"
echo "Web Player:  http://${PI_IP}:8080"
echo ""
echo -e "${GREEN}[✓]${NC} Update complete!"
echo -e "${BLUE}===========================================${NC}"
