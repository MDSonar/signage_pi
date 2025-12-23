#!/bin/bash
###############################################################################
# Signage Pi - Uninstaller for Raspberry Pi 4B
# Usage: sudo bash uninstall-signage-pi.sh
#
# This script:
# - Stops and disables systemd services
# - Removes systemd service files
# - Removes application directory
# - Optionally removes Python virtual environment
# - Optionally removes FTP user and data
###############################################################################

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
APP_HOME="/opt/signage-pi"
SIGNAGE_HOME="${HOME}/.signage"
FTP_USER="signage"

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[✓]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check root
if [[ $EUID -ne 0 ]]; then
    log_error "This script must be run as root (use: sudo bash uninstall-signage-pi.sh)"
    exit 1
fi

log_info "=========================================="
log_info "Signage Pi Uninstaller"
log_info "=========================================="
log_info ""

# Confirm
read -p "This will remove Signage Pi. Continue? (y/N): " -r
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    log_info "Uninstall cancelled."
    exit 0
fi

# 1. Stop and disable services
log_info "Step 1: Stopping services..."
systemctl stop signage-dashboard.service 2>/dev/null || true
systemctl stop signage-web-player.service 2>/dev/null || true
systemctl disable signage-dashboard.service 2>/dev/null || true
systemctl disable signage-web-player.service 2>/dev/null || true
log_success "Services stopped and disabled"

# 2. Remove service files
log_info "Step 2: Removing service files..."
rm -f /etc/systemd/system/signage-dashboard.service
rm -f /etc/systemd/system/signage-web-player.service
systemctl daemon-reload
log_success "Service files removed"

# 3. Remove application directory
log_info "Step 3: Removing application directory..."
if [ -d "$APP_HOME" ]; then
    rm -rf "$APP_HOME"
    log_success "Application directory removed"
else
    log_warn "Application directory not found: $APP_HOME"
fi

# 4. Ask about data removal
read -p "Remove Signage data directory ($SIGNAGE_HOME)? (y/N): " -r
if [[ $REPLY =~ ^[Yy]$ ]]; then
    if [ -d "$SIGNAGE_HOME" ]; then
        rm -rf "$SIGNAGE_HOME"
        log_success "Data directory removed"
    fi
else
    log_info "Keeping data directory for recovery"
fi

# 5. Ask about FTP user removal
read -p "Remove FTP user '$FTP_USER'? (y/N): " -r
if [[ $REPLY =~ ^[Yy]$ ]]; then
    if id "$FTP_USER" &>/dev/null; then
        userdel -r "$FTP_USER" 2>/dev/null || true
        log_success "FTP user removed"
    fi
    rm -f /etc/vsftpd.chroot_list
fi

log_info "=========================================="
log_success "Uninstallation complete!"
log_info "=========================================="
echo ""
echo "Remaining items (if any):"
echo "  - Installed packages (Python, ffmpeg, vsftpd)"
echo "  - systemd journal logs"
echo ""
echo "To remove all packages, run:"
echo "  sudo apt-get autoremove"
echo ""
