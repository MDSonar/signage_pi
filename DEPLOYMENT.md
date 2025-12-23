# Signage Pi - Deployment Guide for Raspberry Pi 4B

## Quick Start (One-Command Installation)

### Prerequisites
- **Hardware:** Raspberry Pi 4B (2GB/4GB/8GB RAM)
- **OS:** Raspberry Pi OS (32-bit or 64-bit) - freshly imaged
- **Network:** Ethernet or WiFi connectivity
- **SSH Access:** Enable SSH on first boot or via Raspberry Pi Imager

### One-Step Installation

On your blank Raspberry Pi, clone the repo and run the installer:

```bash
# Clone the repository
git clone https://github.com/your-org/project.git
cd project/signage_pi

# Run the installer (includes all dependencies, FTP server, services)
sudo bash scripts/install-signage-pi.sh $(pwd)
```

**That's it!** The installer will:
- ✅ Update system packages
- ✅ Install Python, ffmpeg, and FTP server (vsftpd)
- ✅ Create Python virtual environment at `/opt/signage-pi`
- ✅ Install all Python dependencies
- ✅ Set up `~/.signage/` directory structure for content and cache
- ✅ Install and enable systemd services for Dashboard and Web Player
- ✅ Configure FTP server with auto-generated credentials
- ✅ Start both services and enable auto-start on reboot

### Post-Installation

The installer outputs your access details:

```
=== Access Points ===
Dashboard:        http://<pi-ip>:5000
Web Player:       http://<pi-ip>:8080

=== FTP Access ===
Server:           <pi-ip>
Port:             21
Username:         signage
Password:         (generated randomly)
Directory:        ~/.signage/
```

**Login to Dashboard:**
- Default user: `admin`
- Default password: `signage`

**Upload Content via FTP:**
- Connect with FTP client (e.g., FileZilla, WinSCP)
- Upload videos to: `content/videos/`
- Upload presentations to: `content/presentations/`
- Files appear in Dashboard automatically

---

## Manual Installation (If Needed)

If you prefer step-by-step or need customization:

### 1. Install System Dependencies

```bash
sudo apt update
sudo apt install -y \
    python3-venv \
    python3-dev \
    ffmpeg \
    vsftpd \
    git \
    curl
```

### 2. Create App Directory

```bash
sudo mkdir -p /opt/signage-pi
sudo mkdir -p ~/.signage/{content/videos,content/presentations,cache/slides,logs,commands}
sudo chown -R pi:pi ~/.signage
```

### 3. Clone Repository

```bash
cd /opt/signage-pi
sudo git clone https://github.com/your-org/project.git .
```

### 4. Create Python Virtual Environment

```bash
cd /opt/signage-pi
sudo python3 -m venv venv
sudo source venv/bin/activate
sudo pip install --upgrade pip
sudo pip install -r requirements.txt
sudo deactivate
```

### 5. Install Systemd Services

```bash
sudo cp signage-dashboard.service /etc/systemd/system/
sudo cp signage-web-player.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable signage-dashboard signage-web-player
sudo systemctl start signage-dashboard signage-web-player
```

### 6. Configure FTP Server

```bash
# Create FTP user
sudo useradd -m -s /usr/sbin/nologin -d ~/.signage signage
sudo passwd signage  # Set password when prompted

# Configure vsftpd (edit /etc/vsftpd.conf)
sudo systemctl restart vsftpd
```

---

## Service Management

### View Service Status

```bash
sudo systemctl status signage-dashboard
sudo systemctl status signage-web-player
```

### View Live Logs

```bash
# Dashboard logs
sudo journalctl -u signage-dashboard -f

# Web Player logs
sudo journalctl -u signage-web-player -f

# All Signage logs
sudo journalctl -u "signage-*" -f
```

### Restart Services

```bash
sudo systemctl restart signage-dashboard
sudo systemctl restart signage-web-player
```

### Stop Services

```bash
sudo systemctl stop signage-dashboard
sudo systemctl stop signage-web-player
```

---

## Performance Tuning

### Worker Configuration

Edit `/etc/systemd/system/signage-dashboard.service` or `/etc/systemd/system/signage-web-player.service` and adjust:

- **Dashboard:** `--workers 2` (admin/upload, fewer workers OK)
- **Web Player:** `--workers 4` (streaming, more workers = more concurrent TVs)

**For different Pi RAM:**
- **2GB RAM:** Dashboard 1-2 workers, Web Player 2-3 workers
- **4GB RAM:** Dashboard 2 workers, Web Player 4-6 workers (supports 8-12 TVs)
- **8GB RAM:** Dashboard 2-4 workers, Web Player 8-10 workers (supports 15-20+ TVs)

After editing, reload and restart:

```bash
sudo systemctl daemon-reload
sudo systemctl restart signage-dashboard signage-web-player
```

### Playlist Caching

Caching is enabled by default and set to 5-second TTL in `web_player.py`:

```python
PLAYLIST_CACHE_TTL = 5  # seconds
```

Reduce for tighter refresh, increase to lower CPU.

### HTTP Cache Headers

Already configured:
- **Playlist API:** 5-second client-side cache
- **Video/Slide Content:** 1-hour client-side cache

---

## Uninstallation

To cleanly remove Signage Pi and keep your data:

```bash
sudo bash scripts/uninstall-signage-pi.sh
```

The script will:
- Stop and disable services
- Remove systemd files
- Remove application directory (`/opt/signage-pi`)
- Optionally remove data (`~/.signage/`)
- Optionally remove FTP user

Your data in `~/.signage/` is preserved unless you choose to remove it.

---

## Troubleshooting

### Services Not Starting

Check logs:

```bash
sudo journalctl -u signage-dashboard -n 50
sudo journalctl -u signage-web-player -n 50
```

Common issues:
- **Port already in use:** Change port in systemd service file
- **Permission denied:** Ensure `/opt/signage-pi` is owned by `pi` user
- **Missing venv:** Re-run installer or create venv manually

### FTP Connection Issues

Verify FTP is running:

```bash
sudo systemctl status vsftpd
```

Test connectivity:

```bash
ftp <pi-ip>
# Login with credentials from installation output
```

### High CPU Usage

Reduce Web Player workers or increase cache TTL:

```bash
# In signage-web-player.service, reduce --workers 4 to --workers 2
sudo systemctl daemon-reload
sudo systemctl restart signage-web-player
```

### Videos Not Playing

Ensure files are in the correct format (H.264/AAC MP4 preferred):

```bash
# Optimize videos via Dashboard:
# POST /optimize/videos (requires admin login)
```

Or manually:

```bash
ffmpeg -i input.mkv -c:v libx264 -preset veryfast -c:a aac output.mp4
```

---

## Monitoring

### Check Disk Usage

```bash
df -h ~/.signage/
du -sh ~/.signage/*/
```

### Monitor System Resources

```bash
top
ps aux | grep gunicorn
```

---

## Backup and Recovery

### Backup Configuration and Content

```bash
# Backup everything under ~/.signage/
tar -czf signage-backup-$(date +%Y%m%d).tar.gz ~/.signage/

# Transfer off Pi via FTP or SCP
scp pi@<pi-ip>:~/signage-backup-*.tar.gz ./
```

### Restore

```bash
tar -xzf signage-backup-*.tar.gz -C ~/
sudo systemctl restart signage-dashboard signage-web-player
```

---

## Updates

To update the application:

```bash
cd /opt/signage-pi
sudo git pull origin main
sudo systemctl restart signage-dashboard signage-web-player
```

If Python dependencies changed:

```bash
sudo source /opt/signage-pi/venv/bin/activate
sudo pip install -r /opt/signage-pi/requirements.txt
sudo deactivate
sudo systemctl restart signage-dashboard signage-web-player
```

---

## Network Access

### Access from Outside Your Local Network

For remote access, use a reverse proxy or VPN:

#### Option 1: SSH Port Forwarding

```bash
ssh -L 5000:localhost:5000 -L 8080:localhost:8080 pi@<pi-ip>
# Then visit http://localhost:5000 and http://localhost:8080
```

#### Option 2: Nginx Reverse Proxy (Optional)

```bash
sudo apt install nginx
# Configure /etc/nginx/sites-available/default with upstream blocks
# pointing to localhost:5000 and localhost:8080
```

#### Option 3: Cloudflare Tunnel (Recommended for secure remote access)

```bash
# Install and configure cloudflared on the Pi
# Tunnels expose local services securely without port forwarding
```

---

## Support

For issues, logs, and advanced configuration:
- Check `/var/log/signage-install.log` for install issues
- Use `journalctl` to view service logs
- Review individual service files in `/etc/systemd/system/signage-*.service`

---

**Version:** 2.0 (Dec 2025)
**Last Updated:** December 23, 2025
