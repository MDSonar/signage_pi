#!/usr/bin/env python3
"""
Digital Signage Web Player
- Serves content as web app for network TVs
- Multiple TVs can connect simultaneously
- Auto-refresh when content changes
"""

from flask import Flask, render_template, send_from_directory, jsonify, make_response, request
from pathlib import Path
import logging
import json
import hashlib
import time
import os
from functools import lru_cache
from threading import Lock

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    psutil = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Performance: Playlist cache with TTL
_playlist_cache = {'data': None, 'hash': None, 'timestamp': 0, 'playlist_mtime': 0.0}
_playlist_cache_lock = Lock()
PLAYLIST_CACHE_TTL = 5  # seconds

# Client tracking (active within the last TTL seconds)
CLIENT_TTL_SECONDS = 60
_client_last_seen = {}
_client_lock = Lock()

CONFIG_FILE = Path.home() / 'signage' / 'config.json'

PLAYLIST_JSON = Path.home() / 'signage' / 'playlist.json'

VIDEOS_DIR = Path.home() / 'signage' / 'content' / 'videos'
PRESENTATIONS_DIR = Path.home() / 'signage' / 'content' / 'presentations'
SLIDES_CACHE_DIR = Path.home() / 'signage' / 'cache' / 'slides'
VIDEO_FORMATS = ['.mp4', '.avi', '.mov', '.mkv', '.webm']
SLIDE_DURATION = 10

def get_video_files():
    files = []
    if VIDEOS_DIR.exists():
        for ext in VIDEO_FORMATS:
            files.extend(VIDEOS_DIR.glob(f"*{ext}"))
            files.extend(VIDEOS_DIR.glob(f"*{ext.upper()}"))
    return sorted(files)

def get_slide_files():
    slides = []
    if SLIDES_CACHE_DIR.exists():
        for presentation_dir in sorted(SLIDES_CACHE_DIR.iterdir()):
            if presentation_dir.is_dir():
                slides.extend(sorted(presentation_dir.glob("slide_*.png")))
    return slides

def get_playlist_uncached():
    """Internal function that builds playlist from scratch."""
    playlist = []
    
    # Mode is hardcoded to 'both' - always play both videos and presentations
    mode = 'both'

    # If a JSON playlist exists, honor it (selected filenames). It should be a list of filenames
    # (videos or presentation filenames). Presentations are expanded to their cached slides.
    selected = []
    try:
        if PLAYLIST_JSON.exists():
            data = json.loads(PLAYLIST_JSON.read_text())
            if isinstance(data, list):
                # normalize to list of objects with repeats
                for entry in data:
                    if isinstance(entry, str):
                        selected.append({'name': entry, 'repeats': 1})
                    elif isinstance(entry, dict):
                        name = entry.get('name') or entry.get('filename')
                        try:
                            repeats = int(entry.get('repeats', 1))
                        except Exception:
                            repeats = 1
                        if name:
                            selected.append({'name': name, 'repeats': max(1, repeats)})
    except Exception:
        logger.exception('Failed to read playlist.json')

    # Build maps
    video_files = {v.name: v for v in get_video_files()}
    # slides are stored under SLIDES_CACHE_DIR/<presentation_stem>/slide_*.png
    if selected:
        logger.info(f"Using JSON playlist with {len(selected)} entries (web player)")
        for entry in selected:
            name = entry.get('name')
            repeats = entry.get('repeats', 1)
            if not name:
                continue
            # Check if item still exists (file not deleted)
            if name in video_files and mode in ('both', 'video'):
                for _ in range(repeats):
                    playlist.append({
                        'type': 'video',
                        'url': f'/content/videos/{video_files[name].name}',
                        'name': video_files[name].name
                    })
            else:
                # treat as presentation filename; expand to slides by stem
                stem = Path(name).stem
                pres_dir = SLIDES_CACHE_DIR / stem
                if pres_dir.exists() and pres_dir.is_dir() and mode in ('both', 'presentation'):
                    for _ in range(repeats):
                        for slide in sorted(pres_dir.glob('slide_*.png')):
                            rel = slide.relative_to(SLIDES_CACHE_DIR)
                            playlist.append({
                                'type': 'image',
                                'url': f'/content/slides/{rel.as_posix()}',
                                'name': slide.name,
                                'duration': SLIDE_DURATION
                            })
                else:
                    # File doesn't exist - skip it
                    logger.warning(f"Skipping orphaned playlist item: {name} (file not found)")
    else:
        for video in get_video_files():
            if mode in ('both', 'video'):
                playlist.append({
                'type': 'video',
                'url': f'/content/videos/{video.name}',
                'name': video.name
                })
        
        for slide in get_slide_files():
            if mode in ('both', 'presentation'):
                relative_path = slide.relative_to(SLIDES_CACHE_DIR)
                playlist.append({
                'type': 'image',
                'url': f'/content/slides/{relative_path.as_posix()}',
                'name': slide.name,
                'duration': SLIDE_DURATION
                })
    
    return playlist

def get_playlist():
    """Get playlist with caching for performance.
    Cache invalidates on TTL or when playlist.json mtime changes.
    """
    now = time.time()
    try:
        pl_mtime = PLAYLIST_JSON.stat().st_mtime if PLAYLIST_JSON.exists() else 0.0
    except Exception:
        pl_mtime = 0.0

    with _playlist_cache_lock:
        expired = (_playlist_cache['data'] is None) or ((now - _playlist_cache['timestamp']) > PLAYLIST_CACHE_TTL)
        changed = (pl_mtime != _playlist_cache.get('playlist_mtime', 0.0))
        if expired or changed:
            # Cache expired or source changed - rebuild
            playlist = get_playlist_uncached()
            playlist_str = json.dumps(playlist, sort_keys=True)
            playlist_hash = hashlib.md5(playlist_str.encode()).hexdigest()
            _playlist_cache['data'] = playlist
            _playlist_cache['hash'] = playlist_hash
            _playlist_cache['timestamp'] = now
            _playlist_cache['playlist_mtime'] = pl_mtime
            logger.debug(f"Playlist cache refreshed (hash: {playlist_hash[:8]}...)")
        return _playlist_cache['data'], _playlist_cache['hash']

def get_playlist_hash():
    _, playlist_hash = get_playlist()
    return playlist_hash

# --- Synchronization helpers (non-breaking additions) ---
# These are used by the optional `/api/playlist-sync` endpoint.
# They are added in a way that does not change the existing `/api/playlist` behavior.

# Global playlist sync state (kept separate so original API is unchanged)
_sync_playlist_cache = None
_sync_playlist_hash_cache = None
_sync_playlist_start_time = None

def get_video_duration(video_path):
    """Get video duration in seconds (placeholder).
    For a production system integrate ffprobe or mediainfo. Using
    a sensible default prevents the sync endpoint from breaking.
    """
    return 30  # default estimate in seconds

def build_playlist_with_durations():
    """Build playlist including per-item durations for sync playback."""
    playlist = []

    # Mode is hardcoded to 'both' - always play both videos and presentations
    mode = 'both'

    for video in get_video_files():
        if mode in ('both', 'video'):
            duration = get_video_duration(video)
            playlist.append({
                'type': 'video',
                'url': f'/content/videos/{video.name}',
                'name': video.name,
                'duration': duration
            })

    for slide in get_slide_files():
        if mode in ('both', 'presentation'):
            relative_path = slide.relative_to(SLIDES_CACHE_DIR)
            playlist.append({
                'type': 'image',
                'url': f'/content/slides/{relative_path.as_posix()}',
                'name': slide.name,
                'duration': SLIDE_DURATION
            })

    return playlist

def get_playlist_hash_from(playlist):
    playlist_str = json.dumps(playlist, sort_keys=True)
    return hashlib.md5(playlist_str.encode()).hexdigest()

def calculate_total_duration(playlist):
    return sum(item.get('duration', 0) for item in playlist)

def get_current_item_index(playlist, elapsed_time):
    total_duration = calculate_total_duration(playlist)
    if total_duration == 0:
        return 0, 0

    position_in_loop = elapsed_time % total_duration
    cumulative = 0
    for idx, item in enumerate(playlist):
        if cumulative + item.get('duration', 0) > position_in_loop:
            item_elapsed = position_in_loop - cumulative
            return idx, item_elapsed
        cumulative += item.get('duration', 0)

    return 0, 0

def get_client_ip():
    """Get client IP, handling proxy headers."""
    return (request.headers.get('X-Forwarded-For') or request.remote_addr or '').split(',')[0].strip()

def track_client():
    """Track active client by IP with last-seen timestamp."""
    client_ip = get_client_ip()
    if not client_ip:
        return
    now = time.time()
    ttl = CLIENT_TTL_SECONDS
    with _client_lock:
        _client_last_seen[client_ip] = now
        # prune stale entries occasionally
        if len(_client_last_seen) > 200:
            cutoff = now - ttl
            for ip, ts in list(_client_last_seen.items()):
                if ts < cutoff:
                    _client_last_seen.pop(ip, None)

def get_active_clients():
    """Return count of clients seen within TTL window."""
    now = time.time()
    cutoff = now - CLIENT_TTL_SECONDS
    with _client_lock:
        # prune and count
        stale = [ip for ip, ts in _client_last_seen.items() if ts < cutoff]
        for ip in stale:
            _client_last_seen.pop(ip, None)
        return len(_client_last_seen)


def get_system_stats():
    """Return lightweight system stats if psutil is available."""
    if not HAS_PSUTIL:
        return None
    stats = {}
    try:
        stats['cpu_percent'] = psutil.cpu_percent(interval=0.1)
    except Exception:
        stats['cpu_percent'] = None
    try:
        vm = psutil.virtual_memory()
        stats['ram_percent'] = vm.percent
        stats['ram_used_gb'] = round(vm.used / (1024 ** 3), 2)
        stats['ram_total_gb'] = round(vm.total / (1024 ** 3), 2)
    except Exception:
        stats['ram_percent'] = None
    # Temperature (best-effort)
    stats['temp_c'] = None
    try:
        temps = psutil.sensors_temperatures()
        if temps:
            for name, entries in temps.items():
                if entries:
                    stats['temp_c'] = round(entries[0].current, 1)
                    break
    except Exception:
        stats['temp_c'] = None
    return stats

@app.route('/')
def player():
    track_client()
    return render_template('web_player.html')

@app.route('/api/playlist')
def api_playlist():
    track_client()
    playlist, playlist_hash = get_playlist()
    response = make_response(jsonify({
        'playlist': playlist,
        'hash': playlist_hash
    }))
    # Cache for 5 seconds on client side
    response.headers['Cache-Control'] = 'public, max-age=5'
    return response

@app.route('/api/status')
def api_status():
    """Return current player status: active clients, playlist info."""
    track_client()
    try:
        playlist, playlist_hash = get_playlist()
        return jsonify({
            'ok': True,
            'active_clients': get_active_clients(),
            'playlist_items': len(playlist),
            'playlist_hash': playlist_hash,
            'timestamp': time.time()
        })
    except Exception:
        logger.exception('Failed to get status')
        return jsonify({'ok': False, 'error': 'server error'}), 500


@app.route('/health')
def health():
    """Lightweight health/status page (JSON or HTML)."""
    try:
        playlist, playlist_hash = get_playlist()
        playlist_items = len(playlist)
    except Exception:
        playlist = []
        playlist_hash = None
        playlist_items = 0

    try:
        pl_mtime = PLAYLIST_JSON.stat().st_mtime if PLAYLIST_JSON.exists() else None
    except Exception:
        pl_mtime = None

    payload = {
        'ok': True,
        'active_clients': get_active_clients(),
        'playlist_items': playlist_items,
        'playlist_hash': playlist_hash,
        'playlist_mtime': pl_mtime,
        'timestamp': time.time(),
        'system_stats': get_system_stats(),
    }

    wants_html = 'text/html' in (request.headers.get('Accept') or '') or request.args.get('html') == '1'
    if wants_html:
        # Simple HTML view
        stats = payload.get('system_stats') or {}
        html = f"""
        <html><body style='font-family: monospace; padding: 12px;'>
        <h3>Signage Health</h3>
        <div>Active clients: {payload['active_clients']}</div>
        <div>Playlist items: {payload['playlist_items']}</div>
        <div>Playlist hash: {payload['playlist_hash']}</div>
        <div>Playlist mtime: {payload['playlist_mtime']}</div>
        <div>CPU%: {stats.get('cpu_percent')}</div>
        <div>RAM%: {stats.get('ram_percent')}</div>
        <div>Temp C: {stats.get('temp_c')}</div>
        <div>Timestamp: {payload['timestamp']}</div>
        </body></html>
        """
        response = make_response(html)
        response.headers['Content-Type'] = 'text/html'
        return response

    return jsonify(payload)


@app.route('/api/playlist-sync')
def api_playlist_sync():
    """Optional synchronized playlist endpoint.
    Returns playlist with durations and server timing so clients can
    align playback. This does not replace the original `/api/playlist`.
    """
    global _sync_playlist_cache, _sync_playlist_hash_cache, _sync_playlist_start_time

    playlist = build_playlist_with_durations()
    playlist_hash = get_playlist_hash_from(playlist)

    # If playlist changed, reset start time
    if playlist_hash != _sync_playlist_hash_cache:
        _sync_playlist_cache = playlist
        _sync_playlist_hash_cache = playlist_hash
        _sync_playlist_start_time = time.time()
        logger.info(f"Playlist updated (sync): {len(playlist)} items")

    if _sync_playlist_start_time and playlist:
        elapsed = time.time() - _sync_playlist_start_time
        current_index, item_elapsed = get_current_item_index(playlist, elapsed)
    else:
        current_index = 0
        item_elapsed = 0

    return jsonify({
        'playlist': playlist,
        'hash': playlist_hash,
        'serverTime': time.time(),
        'playlistStartTime': _sync_playlist_start_time or time.time(),
        'currentIndex': current_index,
        'itemElapsed': item_elapsed
    })


@app.route('/api/command')
def api_command():
    """Return any pending command intended for web players and clear it."""
    try:
        cmdfile = CONFIG_FILE.parent.joinpath('commands', 'web.json')
        if cmdfile.exists():
            try:
                data = json.loads(cmdfile.read_text())
            except Exception:
                data = {}
            # Do NOT delete the command file here — keep it for other connected clients.
            # Clients will deduplicate using the timestamp (ts) value.
            return jsonify({'ok': True, 'command': data})
    except Exception:
        logger.exception('Failed reading command file')
    return jsonify({'ok': True, 'command': None})

@app.route('/content/videos/<path:filename>')
def serve_video(filename):
    response = make_response(send_from_directory(VIDEOS_DIR, filename))
    # Cache videos for 1 hour (they rarely change)
    response.headers['Cache-Control'] = 'public, max-age=3600'
    return response

@app.route('/content/slides/<path:filename>')
def serve_slide(filename):
    response = make_response(send_from_directory(SLIDES_CACHE_DIR, filename))
    # Cache slides for 1 hour
    response.headers['Cache-Control'] = 'public, max-age=3600'
    return response

if __name__ == '__main__':
    logger.info("=" * 60)
    logger.info("Starting Web Player for Network TVs")
    logger.info("TVs should open: http://<pi-ip>:8080")
    logger.info("=" * 60)
    logger.info("NOTE: For production use, run with gunicorn:")
    logger.info("  gunicorn -w 4 -b 0.0.0.0:8080 web_player:app")
    logger.info("=" * 60)
    
    # Enable threading for concurrent requests (development mode only)
    app.run(host='0.0.0.0', port=8080, debug=False, threaded=True)
