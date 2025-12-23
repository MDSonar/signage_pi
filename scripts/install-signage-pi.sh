#!/bin/bash
###############################################################################
# Signage Pi - One-Step Installer for Raspberry Pi 4B
# 
# USAGE (from git repository directory):
#   cd ~/signage_pi
#   sudo bash scripts/install-signage-pi.sh
# 
# WORKFLOW:
#   1. Clone/pull repo on Pi: git clone <repo-url> && cd signage_pi
#   2. Run this installer from repo directory
#   3. For updates: git pull && sudo bash scripts/update-signage-pi.sh
# 
# This script:
# - Detects actual user (not root) via $SUDO_USER
# - Installs system dependencies (Python, ffmpeg, FTP server)
# - Creates Python virtual environment at /opt/signage-pi
# - Installs Python packages
# - Copies code from current directory to /opt/signage-pi
# - Sets up data directory at ~/.signage/ (preserves across updates)
# - Installs and enables systemd services with correct user
# - Configures and starts FTP server for file transfers
###############################################################################

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
REPO_PATH="${1:-.}"
VENV_PATH="/opt/signage-pi/venv"
APP_HOME="/opt/signage-pi"

# Detect actual user (not root when using sudo)
if [ -n "$SUDO_USER" ]; then
    ACTUAL_USER="$SUDO_USER"
    ACTUAL_HOME=$(getent passwd "$SUDO_USER" | cut -d: -f6)
else
    ACTUAL_USER="$USER"
    ACTUAL_HOME="$HOME"
fi

SIGNAGE_HOME="${ACTUAL_HOME}/.signage"
LOG_FILE="/var/log/signage-install.log"
FTP_USER="signage"
FTP_PASS="$(date +%s | sha256sum | base64 | head -c 12)"

# Helper functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1" | tee -a "$LOG_FILE"
}

log_success() {
    echo -e "${GREEN}[✓]${NC} $1" | tee -a "$LOG_FILE"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1" | tee -a "$LOG_FILE"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1" | tee -a "$LOG_FILE"
}

# Check root
if [[ $EUID -ne 0 ]]; then
    log_error "This script must be run as root (use: sudo bash install-signage-pi.sh)"
    exit 1
fi

log_info "=========================================="
log_info "Starting Signage Pi Installation"
log_info "=========================================="
log_info "Detected user: $ACTUAL_USER"
log_info "Repo path: $REPO_PATH"
log_info "App home: $APP_HOME"
log_info "Signage home: $SIGNAGE_HOME"
log_info "Python venv: $VENV_PATH"
log_info ""

# 1. Update apt cache
log_info "Step 1: Updating apt cache..."
apt-get update >> "$LOG_FILE" 2>&1
log_success "apt cache updated"

# 2. Install system dependencies
log_info "Step 2: Installing system dependencies..."
apt-get install -y \
    python3-venv \
    python3-dev \
    ffmpeg \
    vsftpd \
    git \
    curl \
    >> "$LOG_FILE" 2>&1
log_success "System dependencies installed"

# 3. Create app directory
log_info "Step 3: Creating app directories..."
mkdir -p "$APP_HOME"
mkdir -p "$SIGNAGE_HOME"/{content/videos,content/presentations,cache/slides,logs,commands}
chown -R "$ACTUAL_USER:$ACTUAL_USER" "$SIGNAGE_HOME"
chmod 755 "$SIGNAGE_HOME"
log_success "Directories created"

# 4. Create Python virtual environment
log_info "Step 4: Creating Python virtual environment..."
python3 -m venv "$VENV_PATH" >> "$LOG_FILE" 2>&1
log_success "Virtual environment created at $VENV_PATH"

# 5. Copy app code to /opt/signage-pi
log_info "Step 5: Copying application code from repo..."
if [ -d "$REPO_PATH" ]; then
    cp -f "$REPO_PATH"/*.py "$APP_HOME/" 2>/dev/null || true
    cp -rf "$REPO_PATH"/templates "$APP_HOME/" 2>/dev/null || true
    cp -f "$REPO_PATH"/requirements.txt "$APP_HOME/" 2>/dev/null || true
    cp -f "$REPO_PATH"/start_*.sh "$APP_HOME/" 2>/dev/null || true
    chmod +x "$APP_HOME"/start_*.sh 2>/dev/null || true
    chown -R root:root "$APP_HOME"
    log_success "App code copied to $APP_HOME"
else
    log_error "Repo path not found: $REPO_PATH"
    exit 1
fi

# 6. Install Python requirements
log_info "Step 6: Installing Python requirements..."
source "$VENV_PATH/bin/activate"
pip install --upgrade pip >> "$LOG_FILE" 2>&1
pip install -r "$APP_HOME/requirements.txt" >> "$LOG_FILE" 2>&1
deactivate
log_success "Python dependencies installed"

# 7. Install systemd services
log_info "Step 7: Installing systemd services..."
cp "$REPO_PATH/signage-dashboard.service" /etc/systemd/system/signage-dashboard.service
cp "$REPO_PATH/signage-web-player.service" /etc/systemd/system/signage-web-player.service

# Update service files with correct user and paths
sed -i "s|User=pi|User=$ACTUAL_USER|g" /etc/systemd/system/signage-dashboard.service
sed -i "s|Group=pi|Group=$ACTUAL_USER|g" /etc/systemd/system/signage-dashboard.service
sed -i "s|/home/pi/.local/bin|$VENV_PATH/bin|g" /etc/systemd/system/signage-dashboard.service
sed -i "s|/home/pi/signage_pi|$APP_HOME|g" /etc/systemd/system/signage-dashboard.service
sed -i "s|/home/pi/.signage|$SIGNAGE_HOME|g" /etc/systemd/system/signage-dashboard.service
sed -i "s|HOME=/home/pi|HOME=$ACTUAL_HOME|g" /etc/systemd/system/signage-dashboard.service

sed -i "s|User=pi|User=$ACTUAL_USER|g" /etc/systemd/system/signage-web-player.service
sed -i "s|Group=pi|Group=$ACTUAL_USER|g" /etc/systemd/system/signage-web-player.service
sed -i "s|/home/pi/.local/bin|$VENV_PATH/bin|g" /etc/systemd/system/signage-web-player.service
sed -i "s|/home/pi/signage_pi|$APP_HOME|g" /etc/systemd/system/signage-web-player.service
sed -i "s|/home/pi/.signage|$SIGNAGE_HOME|g" /etc/systemd/system/signage-web-player.service
sed -i "s|HOME=/home/pi|HOME=$ACTUAL_HOME|g" /etc/systemd/system/signage-web-player.service

systemctl daemon-reload
systemctl enable signage-dashboard.service
systemctl enable signage-web-player.service
log_success "Systemd services installed and enabled"

# 8. Setup FTP server
log_info "Step 8: Configuring FTP server (vsftpd)..."

# Create FTP user
if ! id "$FTP_USER" &>/dev/null; then
    useradd -m -s /usr/sbin/nologin -d "$SIGNAGE_HOME" "$FTP_USER"
    echo "$FTP_USER:$FTP_PASS" | chpasswd
    log_success "FTP user created: $FTP_USER"
else
    log_warn "FTP user '$FTP_USER' already exists"
fi

# Configure vsftpd
cat > /etc/vsftpd.conf << 'VSFTPD_CONFIG'
listen=YES
listen_ipv6=NO
anonymous_enable=NO
local_enable=YES
write_enable=YES
local_umask=022
dirmessage_enable=YES
use_localtime=YES
xferlog_enable=YES
xferlog_file=/var/log/vsftpd.log
xferlog_std_format=NO
idle_session_timeout=600
data_connection_timeout=120
nopriv_user=nobody
chroot_local_user=YES
chroot_list_enable=YES
chroot_list_file=/etc/vsftpd.chroot_list
allow_writeable_chroot=YES
pasv_enable=YES
pasv_min_port=6000
pasv_max_port=6100
force_local_data_ssl=NO
force_local_logins_ssl=NO
ssl_enable=NO
VSFTPD_CONFIG

# Add FTP user to chroot list
echo "$FTP_USER" > /etc/vsftpd.chroot_list

# Set FTP home permissions
chown -R "$FTP_USER:$FTP_USER" "$SIGNAGE_HOME"
chmod -R 755 "$SIGNAGE_HOME"

systemctl restart vsftpd
log_success "FTP server configured and started"

# 9. Start services
log_info "Step 9: Starting services..."
systemctl start signage-dashboard.service
systemctl start signage-web-player.service
sleep 2

# Check service status
if systemctl is-active --quiet signage-dashboard.service; then
    log_success "Dashboard service is running"
else
    log_warn "Dashboard service failed to start (check logs with: systemctl status signage-dashboard)"
fi

if systemctl is-active --quiet signage-web-player.service; then
    log_success "Web Player service is running"
else
    log_warn "Web Player service failed to start (check logs with: systemctl status signage-web-player)"
fi

# Get Pi IP
PI_IP=$(hostname -I | awk '{print $1}')

# 10. Print summary
log_info "=========================================="
log_success "Installation complete!"
log_info "=========================================="
echo ""
echo -e "${GREEN}=== Access Points ===${NC}"
echo "Dashboard:        http://${PI_IP}:5000"
echo "Web Player:       http://${PI_IP}:8080"
echo ""
echo -e "${GREEN}=== FTP Access ===${NC}"
echo "Server:           ${PI_IP}"
echo "Port:             21"
echo "Username:         ${FTP_USER}"
echo "Password:         ${FTP_PASS}"
echo "Directory:        ${SIGNAGE_HOME}"
echo ""
echo -e "${GREEN}=== Useful Commands ===${NC}"
echo "View logs:"
echo "  Dashboard:  sudo journalctl -u signage-dashboard -f"
echo "  Web Player: sudo journalctl -u signage-web-player -f"
echo ""
echo "Restart services:"
echo " pdate installation (after git pull):"
echo "  cd ~/signage_pi && git pull"
echo "  sudo bash scripts/update-signage-pi.sh"
echo ""
echo "Uninstall:"
echo "  sudo bash scriptsgnage-web-player"
echo ""
echo "Uninstall:"
echo "  sudo bash $(dirname "$0")/uninstall-signage-pi.sh"
echo ""
echo -e "${YELLOW}IMPORTANT: Save the FTP credentials above securely!${NC}"
echo ""
log_info "Log file: $LOG_FILE"
