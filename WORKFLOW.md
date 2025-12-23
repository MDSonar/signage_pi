# Development & Deployment Workflow

## Standard Workflow: Git Pull → Deploy

### First-Time Installation

```bash
# On your Raspberry Pi
git clone https://github.com/your-org/signage_pi.git
cd signage_pi
sudo bash scripts/install-signage-pi.sh
```

**What happens:**
- Detects your username (e.g., `sonar`, not `pi`)
- Installs system dependencies (ffmpeg, Python, FTP server)
- Creates `/opt/signage-pi` (application files)
- Creates `~/.signage/` (your data - videos, presentations, cache)
- Sets up systemd services with your username
- Starts services automatically

### Updates & Redeployment

```bash
# Pull latest code
cd ~/signage_pi
git pull

# Redeploy
sudo bash scripts/update-signage-pi.sh
```

**What happens:**
- Stops services
- Copies new code to `/opt/signage-pi`
- Updates Python dependencies
- Updates systemd services (if changed)
- Restarts services
- **Preserves all data in `~/.signage/`**

### Fix Broken Installation

If installation fails with user permission errors:

```bash
cd ~/signage_pi
sudo bash scripts/fix-user-permissions.sh
```

This fixes:
- Wrong user in systemd services
- Data in `/root/.signage` instead of your home
- Permission issues

---

## Directory Structure

### Application Files (Updated on Deploy)
```
/opt/signage-pi/
├── venv/              # Python virtual environment
├── dashboard.py       # Admin interface
├── web_player.py      # TV player
├── player.py          # Legacy VLC player
├── templates/         # HTML templates
└── start_*.sh         # Startup scripts
```

### Data Files (Preserved Across Updates)
```
~/.signage/            # Your actual user home
├── content/
│   ├── videos/        # Upload MP4, AVI, MOV, etc.
│   └── presentations/ # Upload PPTX, PPT, PDF
├── cache/
│   └── slides/        # Auto-generated PNG slides
├── logs/              # Application logs
├── commands/          # Control files
├── config.json        # Settings
└── playlist.json      # Playlist order
```

**Key Point**: `~/.signage/` is YOUR data. It stays safe during updates.

---

## Development Workflow

### Local Testing (Windows/Mac)

```bash
# Install dependencies
pip install -r requirements.txt

# Run dashboard
python dashboard.py    # http://localhost:5000

# Run web player
python web_player.py   # http://localhost:8080
```

### Testing on Raspberry Pi

```bash
# View logs
sudo journalctl -u signage-dashboard -f
sudo journalctl -u signage-web-player -f

# Restart services
sudo systemctl restart signage-dashboard
sudo systemctl restart signage-web-player

# Check status
sudo systemctl status signage-dashboard
sudo systemctl status signage-web-player

# Test endpoints
curl http://localhost:8080/api/playlist
```

---

## Upload Content

### Via FTP
```
Server: <pi-ip>
Port: 21
User: signage
Password: (from installer output)

Upload to:
- content/videos/       → MP4, AVI, MOV, MKV, WEBM
- content/presentations/ → PPTX, PPT, PDF
```

Files appear in dashboard automatically.

### Via Dashboard
1. Login: http://<pi-ip>:5000
2. Username: `admin` / Password: `signage`
3. Upload files via web interface

---

## Common Commands

```bash
# Update from git
cd ~/signage_pi && git pull
sudo bash scripts/update-signage-pi.sh

# Check disk space
du -sh ~/.signage/*/

# Clear presentation cache
rm -rf ~/.signage/cache/slides/*

# View playlist
cat ~/.signage/playlist.json

# Backup data
tar -czf backup-$(date +%Y%m%d).tar.gz ~/.signage/

# Uninstall (keeps data)
sudo bash scripts/uninstall-signage-pi.sh
```

---

## Troubleshooting

### Services Won't Start
```bash
# Check which user is configured
grep "User=" /etc/systemd/system/signage-*.service

# Should match your username (not 'pi' or 'root')
# Fix if wrong:
sudo bash scripts/fix-user-permissions.sh
```

### Data in Wrong Location
```bash
# Check where services look for data
grep "\.signage" /etc/systemd/system/signage-*.service

# Should be /home/<your-user>/.signage
# Fix if wrong:
sudo bash scripts/fix-user-permissions.sh
```

### Port Already in Use
```bash
# Check what's using the ports
sudo lsof -i :5000
sudo lsof -i :8080

# Kill old processes
sudo systemctl stop signage-dashboard
sudo systemctl stop signage-web-player
```

---

## Best Practices

1. **Always run installers from repo directory**: `cd ~/signage_pi && sudo bash scripts/...`
2. **Use update script after git pull**: Don't manually copy files
3. **Backup before major updates**: `tar -czf backup.tar.gz ~/.signage/`
4. **Test in development first**: Run Python scripts directly before deploying
5. **Check logs after deploy**: `sudo journalctl -u signage-dashboard -n 50`
