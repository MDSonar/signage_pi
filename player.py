#!/usr/bin/env python3
"""
Digital Signage Player with PPTX & PDF Support
- Supports PPTX and PDF presentations
- Videos play first, then all presentation slides
"""

import os
import subprocess
import time
from pathlib import Path
import logging
import json
import signal

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.expanduser('~/signage/logs/player.log')),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

CONTENT_DIR = os.path.expanduser("~/signage/content")
VIDEOS_DIR = os.path.expanduser("~/signage/content/videos")
PRESENTATIONS_DIR = os.path.expanduser("~/signage/content/presentations")
SLIDES_CACHE_DIR = os.path.expanduser("~/signage/cache/slides")
IMAGE_DURATION = 10
SLIDE_DURATION = 10
VIDEO_FORMATS = ['.mp4', '.avi', '.mov', '.mkv', '.webm']
PPT_FORMATS = ['.pptx', '.ppt']
PDF_FORMATS = ['.pdf']
PLAYLIST_FILE = os.path.expanduser("~/signage/playlist.m3u")
PLAYLIST_JSON = os.path.expanduser("~/signage/playlist.json")
CHECK_INTERVAL = 20
CONFIG_FILE = Path.home() / 'signage' / 'config.json'
COMMANDS_DIR = Path.home() / 'signage' / 'commands'
SIGNAGE_COMMAND_FILE = COMMANDS_DIR / 'signage.json'
COMMANDS_DIR.mkdir(parents=True, exist_ok=True)

class PresentationConverter:
    """Handles PPTX and PDF to PNG conversion"""
    
    def __init__(self, cache_dir):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def get_cache_path(self, presentation_file):
        cache_name = presentation_file.stem
        return self.cache_dir / cache_name
    
    def is_cached(self, presentation_file):
        cache_path = self.get_cache_path(presentation_file)
        if not cache_path.exists():
            return False
        png_files = list(cache_path.glob("slide_*.png"))
        return len(png_files) > 0
    
    def convert_pptx_to_pdf(self, pptx_file, output_dir):
        logger.info(f"  Converting PPTX to PDF...")
        cmd = ["libreoffice", "--headless", "--convert-to", "pdf", "--outdir", str(output_dir), str(pptx_file)]
        subprocess.run(cmd, check=True, timeout=120)
        generated_pdf = output_dir / f"{pptx_file.stem}.pdf"
        if not generated_pdf.exists():
            raise FileNotFoundError(f"PDF not generated for {pptx_file.name}")
        return generated_pdf
    
    def convert_pdf_to_png(self, pdf_file, output_dir):
        logger.info(f"  Converting PDF pages to PNG...")
        cmd = ["convert", "-density", "150", "-quality", "90", str(pdf_file), str(output_dir / "slide_%03d.png")]
        subprocess.run(cmd, check=True, timeout=120)
        png_files = sorted(output_dir.glob("slide_*.png"))
        if not png_files:
            raise FileNotFoundError(f"No PNG files generated from {pdf_file.name}")
        return png_files
    
    def convert_pptx(self, pptx_file):
        cache_path = self.get_cache_path(pptx_file)
        cache_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"Converting PPTX: {pptx_file.name}")
        try:
            pdf_file = self.convert_pptx_to_pdf(pptx_file, cache_path)
            png_files = self.convert_pdf_to_png(pdf_file, cache_path)
            pdf_file.unlink()
            logger.info(f"✓ Converted {pptx_file.name}: {len(png_files)} slides")
            return png_files
        except Exception as e:
            logger.error(f"Failed to convert {pptx_file.name}: {e}")
            return []
    
    def convert_pdf(self, pdf_file):
        cache_path = self.get_cache_path(pdf_file)
        cache_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"Converting PDF: {pdf_file.name}")
        try:
            png_files = self.convert_pdf_to_png(pdf_file, cache_path)
            logger.info(f"✓ Converted {pdf_file.name}: {len(png_files)} slides")
            return png_files
        except Exception as e:
            logger.error(f"Failed to convert {pdf_file.name}: {e}")
            return []
    
    def convert_presentation(self, presentation_file):
        ext = presentation_file.suffix.lower()
        if ext in PPT_FORMATS:
            return self.convert_pptx(presentation_file)
        elif ext in PDF_FORMATS:
            return self.convert_pdf(presentation_file)
        else:
            logger.error(f"Unsupported format: {ext}")
            return []
    
    def get_slides(self, presentation_file):
        if not self.is_cached(presentation_file):
            self.convert_presentation(presentation_file)
        cache_path = self.get_cache_path(presentation_file)
        return sorted(cache_path.glob("slide_*.png"))

class SmartPlaylistPlayer:
    def __init__(self):
        self.content_dir = Path(CONTENT_DIR)
        self.videos_dir = Path(VIDEOS_DIR)
        self.presentations_dir = Path(PRESENTATIONS_DIR)
        
        self.content_dir.mkdir(parents=True, exist_ok=True)
        self.videos_dir.mkdir(parents=True, exist_ok=True)
        self.presentations_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Player started")
        logger.info(f"Videos: {VIDEOS_DIR}")
        logger.info(f"Presentations: {PRESENTATIONS_DIR}")
        
        self.vlc_process = None
        self.current_playlist_hash = None
        self.pending_update = False
        self.presentation_converter = PresentationConverter(SLIDES_CACHE_DIR)
    
    def get_video_files(self):
        files = []
        for ext in VIDEO_FORMATS:
            files.extend(self.videos_dir.glob(f"*{ext}"))
            files.extend(self.videos_dir.glob(f"*{ext.upper()}"))
        return sorted(files)
    
    def get_presentation_files(self):
        files = []
        for ext in PPT_FORMATS + PDF_FORMATS:
            files.extend(self.presentations_dir.glob(f"*{ext}"))
            files.extend(self.presentations_dir.glob(f"*{ext.upper()}"))
        return sorted(files)
    
    def build_playlist_items(self):
        playlist_items = []
        
        # Mode is hardcoded to 'both' - always play both videos and presentations
        mode = 'both'

        # If a JSON playlist exists, honor it. Support legacy list-of-strings and
        # the new list-of-objects format: [{'name':..., 'repeats': n}, ...]
        selected = []
        try:
            if os.path.exists(PLAYLIST_JSON):
                with open(PLAYLIST_JSON, 'r') as pf:
                    data = json.load(pf)
                    if isinstance(data, list):
                        # normalize to list of objects
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
        except Exception as e:
            logger.warning(f"Failed to read playlist json: {e}")

        # Build lookup maps for quick file->path resolution
        video_files = self.get_video_files()
        video_map = {v.name: v for v in video_files}
        presentation_files = self.get_presentation_files()
        pres_map = {p.name: p for p in presentation_files}

        total_slides = 0

        if selected:
            logger.info(f"Using JSON playlist with {len(selected)} entries")
            valid_count = 0
            orphaned_count = 0
            for entry in selected:
                name = entry.get('name')
                repeats = entry.get('repeats', 1)
                if not name:
                    continue
                # prefer video if exists
                if name in video_map and mode in ('both', 'video'):
                    for _ in range(repeats):
                        playlist_items.append({'type': 'video', 'path': video_map[name], 'duration': -1})
                    valid_count += 1
                elif name in pres_map and mode in ('both', 'presentation'):
                    slides = self.presentation_converter.get_slides(pres_map[name])
                    for _ in range(repeats):
                        for slide in slides:
                            playlist_items.append({'type': 'slide', 'path': slide, 'duration': SLIDE_DURATION})
                            total_slides += 1
                    valid_count += 1
                else:
                    # File doesn't exist - skip it and warn
                    logger.warning(f"Skipping orphaned playlist item: {name} (file not found)")
                    orphaned_count += 1
            logger.info(f"Added {len([i for i in playlist_items if i['type']=='video'])} videos and {total_slides} slides from playlist.json ({orphaned_count} orphaned items skipped)")
        else:
            # Fallback: previous behavior (all files according to mode)
            for video in video_files:
                if mode in ('both', 'video'):
                    playlist_items.append({'type': 'video', 'path': video, 'duration': -1})
            logger.info(f"Added {len(video_files)} videos to playlist")

            for presentation_file in presentation_files:
                if mode in ('both', 'presentation'):
                    slides = self.presentation_converter.get_slides(presentation_file)
                    for slide in slides:
                        playlist_items.append({'type': 'slide', 'path': slide, 'duration': SLIDE_DURATION})
                        total_slides += 1
            logger.info(f"Added {len(presentation_files)} presentations ({total_slides} slides) to playlist")
        
        return playlist_items
    
    def create_playlist(self, items):
        with open(PLAYLIST_FILE, 'w') as f:
            f.write("#EXTM3U\n")
            for item in items:
                if item['type'] == 'video':
                    f.write(f"#EXTINF:-1,{item['path'].name}\n")
                else:
                    f.write(f"#EXTINF:{item['duration']},{item['path'].name}\n")
                f.write(f"{item['path']}\n")
        logger.info(f"✓ Created playlist with {len(items)} items")
    
    def get_playlist_hash(self, items):
        return hash(tuple(str(item['path']) for item in items))
    
    def start_vlc(self):
        cmd = ["cvlc", "--fullscreen", "--no-video-title-show", "--no-osd", "--no-video-deco", 
            "--video-on-top", "--no-interact", "--play-and-exit", 
            "--image-duration", str(SLIDE_DURATION), PLAYLIST_FILE]
        logger.info("▶ Starting VLC...")
        self.vlc_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    def is_vlc_running(self):
        if not self.vlc_process:
            return False
        return self.vlc_process.poll() is None
    
    def stop_vlc(self):
        if self.vlc_process and self.vlc_process.poll() is None:
            self.vlc_process.terminate()
            try:
                self.vlc_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.vlc_process.kill()
            self.vlc_process = None

    def process_commands_if_any(self):
        try:
            if not SIGNAGE_COMMAND_FILE.exists():
                return
            try:
                data = json.loads(SIGNAGE_COMMAND_FILE.read_text())
            except Exception:
                data = {}
            action = data.get('action')
            logger.info(f"Received command: {action}")
            # remove command file
            try:
                SIGNAGE_COMMAND_FILE.unlink()
            except Exception:
                pass

            if action == 'pause':
                if self.vlc_process and self.is_vlc_running():
                    try:
                        os.kill(self.vlc_process.pid, signal.SIGSTOP)
                        logger.info('Paused VLC')
                    except Exception as e:
                        logger.warning(f'Pause failed: {e}')
            elif action == 'play':
                if self.vlc_process and self.is_vlc_running():
                    try:
                        os.kill(self.vlc_process.pid, signal.SIGCONT)
                        logger.info('Resumed VLC')
                    except Exception as e:
                        logger.warning(f'Resume failed: {e}')
            elif action in ('next', 'prev'):
                # rotate playlist and restart VLC to move to next/prev
                items = self.build_playlist_items()
                if not items:
                    return
                if action == 'next':
                    first = items.pop(0)
                    items.append(first)
                else:  # prev
                    last = items.pop()
                    items.insert(0, last)
                # create playlist and restart
                self.create_playlist(items)
                # restart vlc
                self.stop_vlc()
                time.sleep(0.5)
                self.start_vlc()
                logger.info(f'Action {action} applied')
        except Exception as e:
            logger.error(f'Error processing command: {e}', exc_info=True)
    
    def run(self):
        logger.info("🎬 Starting playlist player with PPTX & PDF support...")
        logger.info(f"📹 Videos from: {VIDEOS_DIR}")
        logger.info(f"📊 Presentations from: {PRESENTATIONS_DIR} (PPTX & PDF)")
        logger.info(f"⏱️  Checking for updates every {CHECK_INTERVAL} seconds")
        
        while True:
            try:
                playlist_items = self.build_playlist_items()
                
                if not playlist_items:
                    logger.warning("⚠️  No content found. Waiting...")
                    self.stop_vlc()
                    time.sleep(10)
                    continue
                
                playlist_hash = self.get_playlist_hash(playlist_items)
                
                if playlist_hash != self.current_playlist_hash:
                    if not self.is_vlc_running():
                        logger.info(f"✓ Updating playlist: {len(playlist_items)} items")
                        self.create_playlist(playlist_items)
                        self.current_playlist_hash = playlist_hash
                        self.start_vlc()
                        self.pending_update = False
                    else:
                        if not self.pending_update:
                            logger.info(f"⏳ Changes detected - will update after current playlist")
                            self.pending_update = True
                
                elif not self.is_vlc_running():
                    if self.pending_update:
                        logger.info(f"✓ Applying updates: {len(playlist_items)} items")
                        self.create_playlist(playlist_items)
                        self.current_playlist_hash = playlist_hash
                        self.pending_update = False
                    else:
                        logger.info("↻ Restarting playlist")
                    self.start_vlc()
                
                # sleep in 1s intervals while polling commands for responsiveness
                for _ in range(int(CHECK_INTERVAL)):
                    self.process_commands_if_any()
                    time.sleep(1)
                
            except KeyboardInterrupt:
                logger.info("⏹️  Stopped by user")
                self.stop_vlc()
                break
            except Exception as e:
                logger.error(f"❌ Error: {e}", exc_info=True)
                time.sleep(10)

if __name__ == "__main__":
    import sys
    # support a one-shot conversion mode: `player.py --convert /path/to/file`
    if len(sys.argv) >= 3 and sys.argv[1] == '--convert':
        target = Path(sys.argv[2])
        converter = PresentationConverter(SLIDES_CACHE_DIR)
        try:
            converter.convert_presentation(target)
            logger.info(f"Conversion finished for: {target}")
            sys.exit(0)
        except Exception as e:
            logger.error(f"Conversion failed for {target}: {e}")
            sys.exit(2)
    else:
        player = SmartPlaylistPlayer()
        player.run()
