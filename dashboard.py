#!/usr/bin/env python3
"""
Digital Signage Web Dashboard
"""

from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_from_directory
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash, generate_password_hash
from functools import wraps
import os
from pathlib import Path
import logging
import time
import shutil  # NEW: For cache deletion
import subprocess
import signal
import sys
import json
from pathlib import PurePath
import platform

# Optional: psutil for system stats (graceful degradation if not installed)
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    psutil = None

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = 'change-this-secret-key-12345'

app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024 * 1024  # 2GB
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

VIDEOS_DIR = Path.home() / 'signage' / 'content' / 'videos'
PRESENTATIONS_DIR = Path.home() / 'signage' / 'content' / 'presentations'
CACHE_DIR = Path.home() / 'signage' / 'cache' / 'slides'  # NEW: Cache directory
CONFIG_FILE = Path.home() / 'signage' / 'config.json'
PLAYLIST_FILE = Path.home() / 'signage' / 'playlist.json'
WEB_PLAYER_PID = Path.home() / 'signage' / 'web_player.pid'
SIGNAGE_PLAYER_PID = Path.home() / 'signage' / 'signage_player.pid'
COMMANDS_DIR = Path.home() / 'signage' / 'commands'
COMMANDS_DIR.mkdir(parents=True, exist_ok=True)
WEB_COMMAND_FILE = COMMANDS_DIR / 'web.json'
SIGNAGE_COMMAND_FILE = COMMANDS_DIR / 'signage.json'
LOGS_DIR = Path.home() / 'signage' / 'logs'
LOGS_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_TMP_DIR = Path.home() / 'signage' / 'uploads_tmp'
UPLOAD_TMP_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_VIDEO_EXTENSIONS = {'.mp4', '.avi', '.mov', '.mkv', '.webm'}
ALLOWED_PPT_EXTENSIONS = {'.pptx', '.ppt', '.pdf'}

USERS = {'admin': generate_password_hash('signage')}

def is_ffmpeg_available():
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        return True
    except Exception:
        return False

def transcode_video(input_path: Path, output_path: Path) -> bool:
    """Transcode a video to H.264/AAC MP4 optimized for web playback.
    Returns True on success.
    """
    cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-c:a", "aac", "-b:a", "128k",
        str(output_path)
    ]
    try:
        subprocess.run(cmd, check=True)
        return True
    except subprocess.CalledProcessError as e:
        logger.error("ffmpeg failed: %s", e)
        return False

def allowed_file(filename, allowed_extensions):
    return Path(filename).suffix.lower() in allowed_extensions

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def get_file_size(filepath):
    size = filepath.stat().st_size
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"

def get_file_format(filepath):
    ext = filepath.suffix.lower()
    if ext == '.pdf':
        return 'PDF'
    elif ext in ['.pptx', '.ppt']:
        return 'PPTX'
    elif ext in ['.mp4', '.avi', '.mov', '.mkv', '.webm']:
        return 'VIDEO'
    return 'UNKNOWN'

# NEW: Helper function to get cache size
def get_cache_size(presentation_name):
    """Get size of cached slides for a presentation"""
    cache_path = CACHE_DIR / Path(presentation_name).stem
    if cache_path.exists() and cache_path.is_dir():
        total_size = sum(f.stat().st_size for f in cache_path.rglob('*') if f.is_file())
        return get_file_size_from_bytes(total_size)
    return "0 B"

def get_file_size_from_bytes(size):
    """Convert bytes to human readable size"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


def read_config():
    try:
        if CONFIG_FILE.exists():
            return json.loads(CONFIG_FILE.read_text())
    except Exception:
        logger.exception('Failed to read config')
    # default
    return {'mode': 'both'}


def read_playlist():
    try:
        if PLAYLIST_FILE.exists():
            return json.loads(PLAYLIST_FILE.read_text())
    except Exception:
        logger.exception('Failed to read playlist')
    return []


def write_playlist(lst):
    try:
        PLAYLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
        PLAYLIST_FILE.write_text(json.dumps(lst))
        return True
    except Exception:
        logger.exception('Failed to write playlist')
        return False


def normalize_playlist_to_objects(raw):
    """Return playlist as list of objects: {'name':..., 'repeats': int}
    Accepts legacy list of strings or list of objects and returns normalized list.
    """
    out = []
    if not raw:
        return out
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                out.append({'name': item, 'repeats': 1})
            elif isinstance(item, dict):
                name = item.get('name') or item.get('filename')
                try:
                    repeats = int(item.get('repeats', 1))
                except Exception:
                    repeats = 1
                if name:
                    out.append({'name': name, 'repeats': max(1, repeats)})
    return out


def playlist_names_set(raw):
    """Return a set of playlist filenames regardless of format."""
    s = set()
    if not raw:
        return s
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                s.add(item)
            elif isinstance(item, dict):
                n = item.get('name') or item.get('filename')
                if n:
                    s.add(n)
    return s


def item_exists(name):
    """Check if a playlist item (video or presentation) exists on disk.
    Returns True if the file exists in videos or presentations directory.
    """
    if not name:
        return False
    # Check videos
    video_path = VIDEOS_DIR / name
    if video_path.exists():
        return True
    # Check presentations
    pres_path = PRESENTATIONS_DIR / name
    if pres_path.exists():
        return True
    return False


def filter_valid_playlist(playlist):
    """Remove orphaned items from playlist that no longer exist on disk.
    Returns cleaned playlist and list of removed items.
    """
    normalized = normalize_playlist_to_objects(playlist)
    valid_items = []
    removed_items = []
    
    for item in normalized:
        name = item.get('name')
        if name and item_exists(name):
            valid_items.append(item)
        elif name:
            removed_items.append(name)
            logger.warning(f"Removed orphaned playlist item: {name} (file not found)")
    
    return valid_items, removed_items


def write_config(cfg: dict):
    try:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(cfg))
        return True
    except Exception:
        logger.exception('Failed to write config')
        return False


def get_pid_from_pidfile(pidfile: Path):
    try:
        if not pidfile.exists():
            return None
        raw = pidfile.read_text().strip()
        return int(raw)
    except Exception:
        return None


def is_process_running(pidfile: Path, expected_cmd_substr: str = None):
    """Return True if the PID exists and (optionally) matches an expected command substring.
    On Linux, verifies /proc/<pid>/cmdline contains expected_cmd_substr. This prevents stale pidfiles.
    """
    pid = get_pid_from_pidfile(pidfile)
    if not pid:
        return False
    try:
        # Check process exists
        os.kill(pid, 0)
    except Exception:
        return False
    if expected_cmd_substr:
        try:
            cmdline = Path(f"/proc/{pid}/cmdline").read_text().replace('\x00', ' ')
            return expected_cmd_substr in cmdline
        except Exception:
            return False
    return True


def start_process(cmd: list, pidfile: Path):
    try:
        # For Raspberry Pi (POSIX), create a new session (process group leader)
        # so we can kill the entire group later.
        stdout_log = LOGS_DIR / f"{Path(cmd[-1]).stem}.out.log"
        stderr_log = LOGS_DIR / f"{Path(cmd[-1]).stem}.err.log"
        logger.info("Starting process: %s, stdout=%s, stderr=%s", cmd, stdout_log, stderr_log)
        proc = subprocess.Popen(cmd, stdout=open(stdout_log, 'ab'), stderr=open(stderr_log, 'ab'), preexec_fn=os.setsid, close_fds=True)
        pidfile.parent.mkdir(parents=True, exist_ok=True)
        pidfile.write_text(str(proc.pid))
        logger.info(f"Started process {cmd[0]} pid={proc.pid}")
        return True
    except Exception:
        logger.exception('Failed to start process')
        return False


def stop_process(pidfile: Path):
    try:
        if not pidfile.exists():
            return False
        raw = pidfile.read_text().strip()
        pid = int(raw)

        # Try graceful terminate of the process group (we started with setsid)
        try:
            os.killpg(pid, signal.SIGTERM)
        except Exception:
            try:
                os.kill(pid, signal.SIGTERM)
            except Exception:
                logger.warning('Failed to SIGTERM pid/pgrp=%s', pid)

        # wait a short time for process to exit
        for _ in range(10):
            try:
                os.kill(pid, 0)
                time.sleep(0.2)
            except Exception:
                break

        # If still running, force kill the group
        try:
            os.killpg(pid, signal.SIGKILL)
        except Exception:
            try:
                os.kill(pid, signal.SIGKILL)
            except Exception:
                logger.warning('Failed to SIGKILL pid/pgrp=%s', pid)

        try:
            pidfile.unlink()
        except Exception:
            pass

        logger.info(f"Stopped pid={pid}")
        return True
    except Exception:
        logger.exception('Failed to stop process')
        try:
            pidfile.unlink(missing_ok=True)
        except Exception:
            pass
        return False


# Serve static files (logos, etc) from ~/signage/logo
@app.route('/static/<path:filename>')
def serve_static(filename):
    logo_dir = Path.home() / 'signage' / 'logo'
    logo_dir.mkdir(parents=True, exist_ok=True)
    return send_from_directory(logo_dir, filename)


@app.route('/control/send_command', methods=['POST'])
@login_required
def send_command():
    target = request.form.get('target')  # 'web' or 'signage'
    action = request.form.get('action')  # 'next','prev','pause','play'
    if target not in ('web', 'signage') or action not in ('next','prev','pause','play'):
        flash('Invalid command', 'error')
        return redirect(url_for('dashboard'))

    cmdfile = WEB_COMMAND_FILE if target == 'web' else SIGNAGE_COMMAND_FILE
    try:
        cmdfile.write_text(json.dumps({'action': action, 'ts': time.time()}))
        flash(f'Sent {action} to {target}', 'success')
    except Exception:
        logger.exception('Failed to write command')
        flash('Failed to send command', 'error')
    return redirect(url_for('dashboard'))


@app.route('/optimize/video/<filename>', methods=['POST'])
@login_required
def optimize_single_video(filename):
    """Optimize a single video using ffmpeg and replace it in-place on success."""
    try:
        if not is_ffmpeg_available():
            flash('ffmpeg is not installed on this system.', 'error')
            return redirect(url_for('dashboard'))

        src = VIDEOS_DIR / filename
        if not src.exists():
            flash('Video not found.', 'error')
            return redirect(url_for('dashboard'))

        tmp_out = src.with_suffix('').with_name(src.stem + '_h264.mp4')
        ok = transcode_video(src, tmp_out)
        if not ok:
            if tmp_out.exists():
                try:
                    tmp_out.unlink()
                except Exception:
                    pass
            flash('Transcoding failed.', 'error')
            return redirect(url_for('dashboard'))

        # Replace original file atomically
        backup = src.with_suffix(src.suffix + '.bak')
        try:
            src.rename(backup)
            tmp_out.rename(VIDEOS_DIR / (src.stem + '.mp4'))
            # Remove backup on success
            try:
                backup.unlink()
            except Exception:
                pass
        except Exception as e:
            logger.exception('Failed to replace original after transcoding')
            flash('File replace failed after transcoding.', 'error')
            return redirect(url_for('dashboard'))

        flash(f'Optimized video: {filename}', 'success')
        return redirect(url_for('dashboard'))
    except Exception as e:
        logger.error('Optimize video error: %s', e, exc_info=True)
        flash('Unexpected error optimizing video.', 'error')
        return redirect(url_for('dashboard'))


@app.route('/optimize/videos', methods=['POST'])
@login_required
def optimize_all_videos():
    """Batch optimize all videos; skips files already .mp4 to avoid endless churn.
    """
    if not is_ffmpeg_available():
        flash('ffmpeg is not installed on this system.', 'error')
        return redirect(url_for('dashboard'))

    optimized = 0
    failed = 0
    try:
        for file in sorted(VIDEOS_DIR.glob('*')):
            if not file.is_file():
                continue
            # Only attempt for common video formats not already optimized
            if file.suffix.lower() not in ALLOWED_VIDEO_EXTENSIONS:
                continue
            # Create output path
            out = file.with_suffix('').with_name(file.stem + '_h264.mp4')
            ok = transcode_video(file, out)
            if ok:
                try:
                    backup = file.with_suffix(file.suffix + '.bak')
                    file.rename(backup)
                    out.rename(VIDEOS_DIR / (file.stem + '.mp4'))
                    try:
                        backup.unlink()
                    except Exception:
                        pass
                    optimized += 1
                except Exception:
                    logger.exception('Post-transcode replace failed for %s', file.name)
                    failed += 1
            else:
                failed += 1
    except Exception:
        logger.exception('Batch optimize encountered an error')
        flash('Batch optimize failed (see logs).', 'error')
        return redirect(url_for('dashboard'))

    flash(f'Optimize complete. OK: {optimized}, Failed: {failed}', 'success' if failed == 0 else 'warning')
    return redirect(url_for('dashboard'))


@app.route('/upload_chunk/<content_type>', methods=['POST'])
@login_required
def upload_chunk(content_type):
    """Receive a chunked upload. Expects form-data fields:
    - file: the binary chunk
    - filename: original filename
    - index: zero-based chunk index
    - total: total number of chunks
    The server writes chunks to UPLOAD_TMP_DIR/<secure_filename(filename)>/part_<index>
    When the last chunk is received, the server assembles the parts into the final file
    and triggers the same background conversion logic used by the normal upload endpoint.
    """
    if content_type not in ('video', 'presentation'):
        return jsonify({'ok': False, 'error': 'invalid content type'}), 400

    if 'file' not in request.files:
        return jsonify({'ok': False, 'error': 'no file part'}), 400

    file = request.files['file']
    filename = request.form.get('filename') or file.filename
    try:
        index = int(request.form.get('index', 0))
        total = int(request.form.get('total', 1))
    except Exception:
        return jsonify({'ok': False, 'error': 'invalid index/total'}), 400

    safe_name = secure_filename(filename)
    tmp_dir = UPLOAD_TMP_DIR / safe_name
    try:
        tmp_dir.mkdir(parents=True, exist_ok=True)
        part_path = tmp_dir / f'part_{index:06d}'
        # Save chunk
        file.save(str(part_path))
        logger.info(f'Received chunk {index+1}/{total} for {safe_name}')

        # If last chunk, assemble
        if index + 1 >= total:
            # Determine final path
            if content_type == 'video':
                target_dir = VIDEOS_DIR
            else:
                target_dir = PRESENTATIONS_DIR
            target_dir.mkdir(parents=True, exist_ok=True)
            final_path = target_dir / safe_name

            # Assemble parts in order
            with final_path.open('wb') as fout:
                for i in range(total):
                    part_file = tmp_dir / f'part_{i:06d}'
                    if not part_file.exists():
                        logger.warning(f'Missing chunk {i} while assembling {safe_name}')
                        continue
                    with part_file.open('rb') as fin:
                        shutil.copyfileobj(fin, fout)

            logger.info(f'Assembled upload to {final_path}')

            # cleanup parts
            try:
                shutil.rmtree(tmp_dir)
            except Exception:
                logger.exception('Failed to cleanup tmp upload dir')

            # If presentation, trigger background conversion like in upload_file
            if content_type == 'presentation':
                try:
                    python = sys.executable or 'python3'
                    script = Path(__file__).parent / 'player.py'
                    subprocess.Popen([python, str(script), '--convert', str(final_path)],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
                    logger.info(f"Spawned background converter for (chunked): {safe_name}")
                except Exception:
                    logger.exception('Failed to spawn converter process for chunked upload')

        return jsonify({'ok': True, 'index': index, 'total': total})
    except Exception:
        logger.exception('Chunk upload failed')
        return jsonify({'ok': False, 'error': 'server error'}), 500

@app.route('/')
def index():
    if 'username' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if username in USERS and check_password_hash(USERS[username], password):
            session['username'] = username
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid credentials', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('username', None)
    flash('Logged out', 'success')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    videos = []
    presentations = []
    playlist = read_playlist()
    
    # Auto-cleanup: filter out orphaned items and save if any were removed
    cleaned_playlist, removed_items = filter_valid_playlist(playlist)
    if removed_items:
        write_playlist(cleaned_playlist)
        playlist = cleaned_playlist
        flash(f"Removed {len(removed_items)} orphaned item(s) from playlist: {', '.join(removed_items[:3])}{'...' if len(removed_items) > 3 else ''}", 'warning')
    
    playlist_set = playlist_names_set(playlist)
    
    try:
        VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
        PRESENTATIONS_DIR.mkdir(parents=True, exist_ok=True)
        
        if VIDEOS_DIR.exists():
            for file in sorted(VIDEOS_DIR.iterdir()):
                if file.is_file() and file.suffix.lower() in ALLOWED_VIDEO_EXTENSIONS:
                    videos.append({
                        'name': file.name,
                        'size': get_file_size(file),
                        'type': 'video',
                        'format': get_file_format(file),
                        'in_playlist': file.name in playlist_set
                    })
        
        if PRESENTATIONS_DIR.exists():
            for file in sorted(PRESENTATIONS_DIR.iterdir()):
                if file.is_file() and file.suffix.lower() in ALLOWED_PPT_EXTENSIONS:
                    presentations.append({
                        'name': file.name,
                        'size': get_file_size(file),
                        'type': 'presentation',
                        'format': get_file_format(file),
                        'in_playlist': file.name in playlist_set
                    })
        
    except Exception as e:
        logger.error(f"Error loading dashboard: {e}", exc_info=True)
        flash('Error loading files', 'error')
    
    # read current config and process status
    web_running = is_process_running(WEB_PLAYER_PID, 'web_player.py')
    signage_running = is_process_running(SIGNAGE_PLAYER_PID, 'player.py')

    return render_template('dashboard.html', 
                        videos=videos, 
                        presentations=presentations, 
                        username=session.get('username'),
                        web_running=web_running,
                        signage_running=signage_running,
                        playlist=playlist,
                        playlist_set=playlist_set)


@app.route('/control/toggle_playlist/<content_type>/<filename>', methods=['POST'])
@login_required
def toggle_playlist(content_type, filename):
    """Toggle a file in/out of the playlist"""
    if content_type not in ('video', 'presentation'):
        return jsonify({'ok': False, 'error': 'invalid content type'}), 400
    
    try:
        raw = read_playlist()
        items = normalize_playlist_to_objects(raw)

        # Check if filename present
        found = None
        for it in items:
            if it.get('name') == filename:
                found = it
                break

        if found:
            # remove all entries matching this name
            items = [it for it in items if it.get('name') != filename]
            in_playlist = False
        else:
            items.append({'name': filename, 'repeats': 1})
            in_playlist = True

        ok = write_playlist(items)
        if ok:
            return jsonify({'ok': True, 'in_playlist': in_playlist, 'filename': filename})
        else:
            return jsonify({'ok': False, 'error': 'failed to save'}), 500
    except Exception as e:
        logger.exception('Failed to toggle playlist')
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/playlist_order', methods=['GET'])
@login_required
def api_playlist_order_get():
    """Return normalized playlist (ordered) as list of objects {name, repeats}."""
    try:
        raw = read_playlist()
        items = normalize_playlist_to_objects(raw)
        return jsonify({'ok': True, 'playlist': items})
    except Exception:
        logger.exception('Failed to return playlist order')
        return jsonify({'ok': False, 'error': 'server error'}), 500


@app.route('/api/playlist_order', methods=['POST'])
@login_required
def api_playlist_order_post():
    """Accept a JSON array of objects {name, repeats} and save as the playlist order."""
    try:
        data = request.get_json()
        if not isinstance(data, list):
            return jsonify({'ok': False, 'error': 'expected a JSON array'}), 400

        normalized = []
        for entry in data:
            if isinstance(entry, str):
                normalized.append({'name': entry, 'repeats': 1})
            elif isinstance(entry, dict):
                name = entry.get('name')
                if not name:
                    continue
                try:
                    repeats = int(entry.get('repeats', 1))
                except Exception:
                    repeats = 1
                normalized.append({'name': name, 'repeats': max(1, repeats)})

        ok = write_playlist(normalized)
        if ok:
            return jsonify({'ok': True, 'playlist': normalized})
        else:
            return jsonify({'ok': False, 'error': 'failed to save'}), 500
    except Exception:
        logger.exception('Failed to save playlist order')
        return jsonify({'ok': False, 'error': 'server error'}), 500


@app.route('/control/start_web_player', methods=['POST'])
@login_required
def start_web_player():
    # Start the web player Flask app in background
    if is_process_running(WEB_PLAYER_PID, 'web_player.py'):
        flash('Web player already running', 'error')
        return redirect(url_for('dashboard'))
    python = sys.executable or 'python3'
    script = Path(__file__).parent / 'web_player.py'
    ok = start_process([python, str(script)], WEB_PLAYER_PID)
    flash('Web player started' if ok else 'Failed to start web player', 'success' if ok else 'error')
    return redirect(url_for('dashboard'))


@app.route('/control/stop_web_player', methods=['POST'])
@login_required
def stop_web_player():
    ok = stop_process(WEB_PLAYER_PID)
    flash('Web player stopped' if ok else 'Failed to stop web player', 'success' if ok else 'error')
    return redirect(url_for('dashboard'))


@app.route('/control/start_signage_player', methods=['POST'])
@login_required
def start_signage_player():
    if is_process_running(SIGNAGE_PLAYER_PID, 'player.py'):
        flash('Signage player already running', 'error')
        return redirect(url_for('dashboard'))
    python = sys.executable or 'python3'
    script = Path(__file__).parent / 'player.py'
    ok = start_process([python, str(script)], SIGNAGE_PLAYER_PID)
    flash('Signage player started' if ok else 'Failed to start signage player', 'success' if ok else 'error')
    return redirect(url_for('dashboard'))


@app.route('/control/stop_signage_player', methods=['POST'])
@login_required
def stop_signage_player():
    ok = stop_process(SIGNAGE_PLAYER_PID)
    flash('Signage player stopped' if ok else 'Failed to stop signage player', 'success' if ok else 'error')
    return redirect(url_for('dashboard'))

@app.route('/upload/<content_type>', methods=['POST'])
@login_required
def upload_file(content_type):
    start_time = time.time()
    
    try:
        logger.info(f"Upload started for {content_type}")
        
        if 'file' not in request.files:
            flash('No file selected', 'error')
            return redirect(url_for('dashboard'))
        
        file = request.files['file']
        
        if file.filename == '':
            flash('No file selected', 'error')
            return redirect(url_for('dashboard'))
        
        if content_type == 'video':
            target_dir = VIDEOS_DIR
            allowed_ext = ALLOWED_VIDEO_EXTENSIONS
        elif content_type == 'presentation':
            target_dir = PRESENTATIONS_DIR
            allowed_ext = ALLOWED_PPT_EXTENSIONS
        else:
            flash('Invalid content type', 'error')
            return redirect(url_for('dashboard'))
        
        file_ext = Path(file.filename).suffix.lower()
        if file_ext not in allowed_ext:
            flash(f'Invalid file type. Allowed: {", ".join(allowed_ext)}', 'error')
            return redirect(url_for('dashboard'))
        
        filename = secure_filename(file.filename)
        filepath = target_dir / filename
        
        # NEW: If presentation exists, delete old cache first
        if content_type == 'presentation' and filepath.exists():
            cache_path = CACHE_DIR / filepath.stem
            if cache_path.exists():
                shutil.rmtree(cache_path)
                logger.info(f"Deleted old cache for: {filename}")
        
        target_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Saving {filename}...")
        file.save(str(filepath))
        
        if filepath.exists():
            elapsed = time.time() - start_time
            file_size = get_file_size(filepath)
            flash(f'✓ Uploaded: {filename} ({file_size}) in {elapsed:.1f}s', 'success')
            logger.info(f"Upload complete: {filename} ({file_size}) in {elapsed:.1f}s")
            # If this is a presentation, trigger conversion in background so player process
            # doesn't need to be running. This ensures conversion happens even if the
            # signage player (HDMI) is stopped.
            if content_type == 'presentation':
                try:
                    python = sys.executable or 'python3'
                    script = Path(__file__).parent / 'player.py'
                    # spawn as detached background process
                    subprocess.Popen([python, str(script), '--convert', str(filepath)],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
                    logger.info(f"Spawned background converter for: {filename}")
                except Exception:
                    logger.exception('Failed to spawn converter process')
        else:
            flash('Upload failed: File not saved', 'error')
            logger.error(f"File not found after save: {filepath}")
        
    except Exception as e:
        elapsed = time.time() - start_time
        flash(f'Upload failed after {elapsed:.1f}s: {str(e)}', 'error')
        logger.error(f"Upload error after {elapsed:.1f}s: {e}", exc_info=True)
    
    return redirect(url_for('dashboard'))

@app.route('/delete/<content_type>/<filename>', methods=['POST'])
@login_required
def delete_file(content_type, filename):
    try:
        source_dir = VIDEOS_DIR if content_type == 'video' else PRESENTATIONS_DIR
        filepath = source_dir / filename
        
        if filepath.exists() and filepath.is_file():
            # NEW: Delete cache folder for presentations
            if content_type == 'presentation':
                cache_path = CACHE_DIR / filepath.stem
                if cache_path.exists() and cache_path.is_dir():
                    try:
                        shutil.rmtree(cache_path)
                        logger.info(f"✓ Deleted cache folder: {cache_path.name}")
                    except Exception as cache_error:
                        logger.warning(f"Failed to delete cache: {cache_error}")
            
            # Delete the file
            filepath.unlink()
            flash(f'✓ Deleted: {filename}', 'success')
            logger.info(f"Deleted {content_type}: {filename}")
        else:
            flash(f'File not found: {filename}', 'error')
            
    except Exception as e:
        flash(f'Delete failed: {str(e)}', 'error')
        logger.error(f"Delete error: {e}", exc_info=True)
    
    return redirect(url_for('dashboard'))

@app.route('/api/system_stats')
@login_required
def api_system_stats():
    """Return system statistics: CPU, RAM, disk, temperature."""
    if not HAS_PSUTIL:
        logger.warning('psutil module not available')
        return jsonify({'ok': False, 'error': 'psutil not installed'}), 503
    
    try:
        stats = {}
        
        # CPU usage
        try:
            stats['cpu_percent'] = psutil.cpu_percent(interval=0.1)
        except Exception:
            stats['cpu_percent'] = None
        
        # RAM usage
        try:
            vm = psutil.virtual_memory()
            stats['ram_percent'] = vm.percent
            stats['ram_used_gb'] = round(vm.used / (1024**3), 2)
            stats['ram_total_gb'] = round(vm.total / (1024**3), 2)
        except Exception:
            stats['ram_percent'] = None
        
        # Disk usage (root /)
        try:
            disk = psutil.disk_usage('/')
            stats['disk_percent'] = disk.percent
            stats['disk_used_gb'] = round(disk.used / (1024**3), 2)
            stats['disk_total_gb'] = round(disk.total / (1024**3), 2)
        except Exception:
            stats['disk_percent'] = None
        
        # Temperature (try Linux thermal zones or system temp)
        stats['temp_c'] = None
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                # Try to get CPU temp from common sources
                for name, entries in temps.items():
                    if name.lower() in ('cpu', 'coretemp', 'k10temp', 'acpitz'):
                        if entries:
                            stats['temp_c'] = round(entries[0].current, 1)
                            break
                # If no CPU temp found, use first available
                if stats['temp_c'] is None and temps:
                    first_key = next(iter(temps))
                    if temps[first_key]:
                        stats['temp_c'] = round(temps[first_key][0].current, 1)
        except Exception:
            pass
        
        # System info
        stats['hostname'] = platform.node()
        stats['platform'] = platform.system()
        
        return jsonify({'ok': True, 'stats': stats})
    except Exception:
        logger.exception('Failed to get system stats')
        return jsonify({'ok': False, 'error': 'server error'}), 500


@app.errorhandler(413)
def too_large(e):
    flash('File too large! Maximum: 2GB', 'error')
    return redirect(url_for('dashboard'))

@app.errorhandler(500)
def internal_error(e):
    flash('Internal error. Check logs.', 'error')
    logger.error(f"Internal error: {e}", exc_info=True)
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    PRESENTATIONS_DIR.mkdir(parents=True, exist_ok=True)
    
    logger.info("=" * 60)
    logger.info("Starting Dashboard...")
    logger.info(f"Max upload: 2GB")
    logger.info(f"System stats (psutil): {'✓ Available' if HAS_PSUTIL else '✗ Not installed'}")
    logger.info("=" * 60)
    logger.info("NOTE: For production use, run with gunicorn:")
    logger.info("  gunicorn -w 2 -b 0.0.0.0:5000 --timeout 300 dashboard:app")
    logger.info("=" * 60)
    
    # Enable threading for concurrent requests (development mode only)
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
