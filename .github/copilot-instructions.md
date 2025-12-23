# Signage Pi - AI Coding Agent Instructions

## Project Overview

Digital signage system for Raspberry Pi 4B with dual-mode playback:
- **Web Player** (`web_player.py`): Network-based streaming to multiple TVs (Flask/Gunicorn, port 8080)
- **Dashboard** (`dashboard.py`): Admin interface for content management (Flask/Gunicorn, port 5000)
- **Legacy Player** (`player.py`): Direct VLC playback mode (rarely used)

## Architecture & Data Flow

### Directory Structure (Critical)
All runtime data lives in `~/.signage/` (or `~/signage/` in older installs):
```
~/.signage/
├── content/
│   ├── videos/          # MP4, AVI, MOV, MKV, WEBM
│   └── presentations/   # PPTX, PPT, PDF (converted to PNG slides)
├── cache/
│   └── slides/          # Generated PNG slides per presentation
│       └── presentation_name/
│           ├── slide_001.png
│           ├── slide_002.png
│           └── ...
├── logs/                # Application and gunicorn logs
├── commands/            # Command files for player control
├── config.json          # Mode configuration (unused, mode hardcoded to 'both')
└── playlist.json        # Playlist order with repeats
```

**Key Pattern**: Python code uses `Path.home() / 'signage'` consistently. Bash scripts use `~/.signage`. Both patterns coexist (transition in progress).

### Playlist System
Controlled by `playlist.json` with two formats:
```json
// Legacy format (still supported)
["video1.mp4", "presentation1.pptx"]

// New format with repeat counts
[
  {"name": "video1.mp4", "repeats": 2},
  {"name": "presentation1.pptx", "repeats": 1}
]
```

**Critical Behavior**:
- Playlist items reference filenames, not paths
- Web player expands presentations to individual cached slides
- Legacy player plays presentations as slide sequences
- Missing files are filtered out with warning logs ("orphaned items")
- All three applications (`dashboard.py`, `web_player.py`, `player.py`) parse `playlist.json` independently

### Content Processing Pipeline

**Presentations (PPTX/PDF)**:
1. Upload to `~/.signage/content/presentations/`
2. Dashboard or player converts via `PresentationConverter` class:
   - PPTX → PDF (LibreOffice) → PNG slides (ImageMagick)
   - PDF → PNG slides (ImageMagick)
3. Slides cached at `~/.signage/cache/slides/<filename_stem>/slide_NNN.png`
4. Cache persists until manual deletion via dashboard

**Videos**:
- Direct upload to `~/.signage/content/videos/`
- Optional H.264/AAC transcode via `transcode_video()` if ffmpeg available
- Served directly by web player

## Production Deployment

### Standard Workflow (Git → Pi)
```bash
# Initial installation
git clone <repo-url> signage_pi
cd signage_pi
sudo bash scripts/install-signage-pi.sh

# Updates/redeployment
cd signage_pi
git pull
sudo bash scripts/update-signage-pi.sh
```

### Services (Raspberry Pi)
Two systemd services in `/etc/systemd/system/`:
- `signage-dashboard.service`: Gunicorn with 2 workers, 300s timeout (large uploads)
- `signage-web-player.service`: Gunicorn with 4 workers, 120s timeout (high concurrency)

**Install via**: `sudo bash scripts/install-signage-pi.sh`
- Must be run from git repository directory
- Detects actual user (via `$SUDO_USER`) to avoid root user issues
- Copies code from repo to `/opt/signage-pi` (application home)
- Creates `~/.signage/` in actual user's home for data (persists across updates)
- Sets up `/opt/signage-pi/venv` virtual environment
- Configures vsftpd FTP server for uploads
- Opens firewall ports 5000 (dashboard) and 8080 (web player) via UFW if available
- Installs systemd services with correct username/paths via `sed` replacements
- Generates random FTP password

**Update via**: `sudo bash scripts/update-signage-pi.sh`
- Run after `git pull` to redeploy
- Preserves `~/.signage/` data and configuration
- Updates application code and services
- Restarts services automatically

### Performance Patterns
**Caching (web_player.py)**:
- Playlist cached for 5 seconds (`PLAYLIST_CACHE_TTL`)
- Thread-safe cache with `Lock` (see `_playlist_cache`, `get_playlist()`)
- Invalidates on TTL expiry OR `playlist.json` mtime change
- HTTP cache headers: `Cache-Control: public, max-age=3600` for videos/slides

**Startup Scripts**:
- `start_web_player_gunicorn.sh`: 4 workers for 10-15+ concurrent TVs
- `start_dashboard_gunicorn.sh`: 2 workers (admin-only traffic)

## Development Patterns

### File Handling
**Upload Flow** (dashboard.py):
```python
# 1. Save to temp directory
tmp_path = UPLOAD_TMP_DIR / secure_filename(file.filename)
file.save(tmp_path)

# 2. Process (transcode videos, convert presentations)
if video: transcode_video(tmp_path, final_path)
if presentation: # Manual conversion trigger or auto-convert

# 3. Move to final location
shutil.move(tmp_path, VIDEOS_DIR / filename)
```

**Allowed Extensions** (critical to match):
- Videos: `.mp4, .avi, .mov, .mkv, .webm`
- Presentations: `.pptx, .ppt, .pdf`

### Authentication
Simple session-based auth in dashboard:
- Single user: `admin` / `signage` (hashed via Werkzeug)
- Secret key: `app.secret_key = 'change-this-secret-key-12345'` (TODO: env var)
- Decorator: `@login_required`

### Error Patterns
**Orphaned Files**: Playlist references deleted content
- Behavior: Skip item, log warning, continue playback
- Implemented in: `filter_valid_playlist()`, `item_exists()`, playlist builders

**Cache Management**: Manual deletion only
- Dashboard provides "Clear Cache" button per presentation
- Uses `shutil.rmtree()` on `CACHE_DIR / presentation_stem`

## Testing & Debugging

### Local Development (Windows/Mac)
```bash
python dashboard.py    # Port 5000, threaded Flask
python web_player.py   # Port 8080, threaded Flask
```

### Production Testing (Raspberry Pi)
```bash
# Via systemd
sudo systemctl status signage-web-player
sudo journalctl -u signage-web-player -f

# Direct gunicorn
./start_web_player_gunicorn.sh
```

### Common Commands
```bash
# Check disk usage
du -sh ~/.signage/*/

# Test playlist generation
curl http://localhost:8080/api/playlist

# Validate ffmpeg
ffmpeg -version
```

## Critical Constraints

1. **No README.md**: All documentation in `DEPLOYMENT.md` and `PERFORMANCE.md`
2. **Mode hardcoded**: `mode = 'both'` throughout (videos + presentations always play)
3. **Path consistency**: Use `Path.home() / 'signage'` in Python, not hardcoded `/home/pi`
4. **User detection**: Installer detects actual user via `$SUDO_USER` (not root) and updates systemd services
5. **Systemd templates**: Service files use `User=pi` as template, replaced by installer with actual username
6. **Dependencies**: `ffmpeg` (video transcode), `libreoffice` (PPTX→PDF), `imagemagick` (PDF→PNG)

## When Modifying

- **Playlist changes**: Update all 3 playlist parsers (dashboard, web_player, player)
- **Directory structure**: Update installer script, systemd services, Python constants
- **Cache logic**: Maintain thread-safety in web_player cache with `Lock`
- **Performance**: Monitor Gunicorn worker count (4 for web player scales to 15+ TVs)
- **FTP uploads**: Files auto-appear in dashboard after upload to `content/` subdirs
