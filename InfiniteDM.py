#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
 InfiniteDM - A Full-Featured, All-In-One Internet Download Manager Clone
=============================================================================

 Everything lives in ONE file: download engine + dark-themed GUI + queue +
 scheduler + clipboard monitor + speed limiter + session persistence.

 Features (mirrors the real Internet Download Manager "full" edition):
   * Multi-segment parallel downloads (split every file into N parts and
     fetch them over separate connections for big speed gains)
   * Pause / Resume (keeps .part files, resumes exactly where it stopped,
     survives an app restart thanks to session persistence)
   * Queue with configurable number of simultaneous downloads
   * Download scheduler (start a download at a chosen date/time)
   * Automatic retry with backoff on transient network errors
   * Global speed limiting (token-bucket based)
   * Clipboard monitor (auto-detects copied download links)
   * Batch add of many URLs at once
   * Auto categorisation into Video / Music / Documents / Compressed /
     Programs / General folders
   * yt-dlp integration for YouTube / Facebook / Vimeo / TikTok / etc.
   * Live progress dialogs (progress bar, speed, ETA, size)
   * Session persistence: incomplete downloads are restored on next launch
   * "Open file" / "Open folder" / "Properties" for every download
   * Options dialog (connections, concurrency, speed cap, download folder)
   * Can be packaged as a standalone .exe via PyInstaller (see BUILD.txt)

 Run:        python InfiniteDM.py
 Package:    pyinstaller --onefile --windowed --icon=icon.ico InfiniteDM.py
"""

import os
import re
import sys
import time
import json
import queue as queue_mod
import shutil
import threading
import subprocess
import urllib.request
import urllib.error
from urllib.parse import urlparse, unquote
from datetime import datetime, timedelta
from collections import deque

# Optional third-party helper libraries (the app works without them, too)
try:
    import yt_dlp
except Exception:
    yt_dlp = None

try:
    import pyperclip
except Exception:
    pyperclip = None

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

APP_NAME = "Infinite DM"
APP_VERSION = "1.0"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

CHUNK = 65536
MEDIA_DOMAINS = ("youtube.com", "youtu.be", "facebook.com", "fb.watch",
                 "vimeo.com", "tiktok.com", "twitch.tv", "dailymotion.com",
                 "instagram.com", "twitter.com", "x.com", "bilibili.com")

# ----------------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------------
def human_size(n):
    """Turn a byte count into a human readable string."""
    try:
        n = float(n)
    except (TypeError, ValueError):
        n = 0.0
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024.0 or unit == "TB":
            return f"{n:.2f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024.0
    return f"{n:.2f} TB"


def human_rate(bps):
    if not bps or bps < 0:
        return "-"
    return human_size(bps) + "/s"


def sanitise_filename(name):
    name = re.sub(r'[\\/*?:"<>|\r\n\t]', "", name).strip().strip(".")
    return name or f"file_{int(time.time())}"


def is_url(text):
    return bool(re.match(r"^https?://", text.strip(), re.I))


def is_media_url(url):
    host = urlparse(url).netloc.lower()
    return any(d in host for d in MEDIA_DOMAINS)


def guess_mime_ext(headers, url, fallback=".mp4"):
    """Rough extension hint from a URL / content-type (raw files only)."""
    ct = (headers.get("Content-Type") or "") .lower()
    mapping = {
        "application/zip": ".zip", "application/x-zip-compressed": ".zip",
        "application/x-rar-compressed": ".rar", "application/x-7z-compressed": ".7z",
        "application/x-tar": ".tar", "application/gzip": ".gz", "application/x-gzip": ".gz",
        "application/x-bzip2": ".bz2",
        "application/pdf": ".pdf", "application/msword": ".doc",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/vnd.ms-excel": ".xls",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
        "text/plain": ".txt", "text/html": ".html", "application/json": ".json",
        "image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp",
        "image/svg+xml": ".svg", "image/bmp": ".bmp", "image/x-icon": ".ico",
        "audio/mpeg": ".mp3", "audio/wav": ".wav", "audio/x-wav": ".wav",
        "audio/aac": ".aac", "audio/flac": ".flac", "audio/mp4": ".m4a", "audio/ogg": ".ogg",
        "video/mp4": ".mp4", "video/x-msvideo": ".avi", "video/x-matroska": ".mkv",
        "video/webm": ".webm", "video/quicktime": ".mov", "video/mpeg": ".mpeg",
        "application/vnd.android.package-archive": ".apk",
        "application/x-msdownload": ".exe", "application/x-msi": ".msi",
        "application/octet-stream": "",
    }
    ext = mapping.get(ct)
    if ext:
        return ext
    return fallback


# ----------------------------------------------------------------------------
# Options (persisted to a small JSON file)
# ----------------------------------------------------------------------------
class Options:
    DEFAULTS = {
        "segments": 6,              # parallel connections per file
        "max_concurrent": 3,        # simultaneous downloads
        "speed_limit": 0,           # bytes/sec, 0 = unlimited
        "clipboard_monitor": True,  # auto-detect copied links
        "retries": 3,               # auto retry count
        "download_dir": None,       # None => ~/Downloads/My_IDM_Downloads
    }

    def __init__(self, path):
        self.path = path
        self.data = dict(self.DEFAULTS)
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                self.data.update({k: v for k, v in loaded.items()
                                  if k in self.DEFAULTS})
        except Exception:
            pass
        if not self.data.get("download_dir"):
            self.data["download_dir"] = os.path.join(
                os.path.expanduser("~"), "Downloads", "My_IDM_Downloads")

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
        except Exception:
            pass


# ----------------------------------------------------------------------------
# Download engine
# ----------------------------------------------------------------------------
class SegmentThread(threading.Thread):
    """Download one contiguous byte range of a file into its own .part file."""

    def __init__(self, engine, task, start, end, part_path, resume_size,
                 completed_cb, error_cb):
        super().__init__(daemon=True)
        self.engine = engine
        self.task = task
        self.seg_start = start
        self.seg_end = end
        self.part_path = part_path
        self.resume_size = resume_size   # bytes already in part_path
        self.completed_cb = completed_cb
        self.error_cb = error_cb

    def run(self):
        range_start = self.seg_start + self.resume_size
        range_end = self.seg_end
        if range_start > range_end:
            self.completed_cb(self)   # already fully downloaded
            return

        headers = {"User-Agent": USER_AGENT,
                   "Range": f"bytes={range_start}-{range_end}"}
        try:
            req = urllib.request.Request(self.task.url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status != 206:
                    raise OSError(f"Server did not honour Range (HTTP {resp.status})")
                mode = "ab" if self.resume_size else "wb"
                self.engine._ensure_dir(os.path.dirname(self.part_path))
                with open(self.part_path, mode) as f:
                    while True:
                        if self._should_stop():
                            return
                        chunk = resp.read(CHUNK)
                        if not chunk:
                            break
                        # stop check between read and write, so we don't lose
                        # the tail on pause
                        f.write(chunk)
                        self.engine._on_bytes(self.task, len(chunk))
            self.completed_cb(self)
        except urllib.error.HTTPError as e:
            self.error_cb(self, f"HTTP {e.code}")
        except urllib.error.URLError as e:
            self.error_cb(self, str(e.reason))
        except Exception as e:
            if self._should_stop():
                return
            self.error_cb(self, str(e))

    def _should_stop(self):
        if (self.engine._stop_event(self.task)):
            return True
        return False


class DownloadTask:
    """State object for a single download."""

    def __init__(self, task_id, url, filename=None, size=0, save_path=None):
        self.task_id = task_id
        self.url = url
        self.filename = filename or f"file_{int(time.time())}"
        self.size = size
        self.save_path = save_path
        self.dir = None
        self.status = "Idle"        # Idle, Queued, Connecting, Downloading,
                                    # Paused, Complete, Error, Merging, Merged
        self.downloaded = 0
        self.speed = 0.0
        self.eta = 0.0
        self.percent = 0.0
        self.error = ""
        self.retries = 0
        self.scheduled_at = None
        self.started_at = None
        self.finished_at = None
        self.pause_requested = False
        self.cancel_requested = False
        self._last_push = 0.0
        self._samples = deque(maxlen=15)
        self._running_threads = 0
        lock = threading.RLock()
        self.lock = lock


class DownloadEngine:
    """GUI-agnostic engine. Talks to the UI through an event queue."""

    def __init__(self, options, event_queue=None):
        self.options = options
        self.events = event_queue or queue_mod.Queue()
        self.tasks = {}
        self._bucket_rate = float(options.data.get("speed_limit", 0) or 0)
        self._bucket = 0.0
        self._buck_last = time.time()
        self._buck_lock = threading.Lock()
        self._parts_dir = None
        self._state_lock = threading.Lock()

    # --- directory helpers ------------------------------------------------
    def base_dir(self):
        return self.options.data["download_dir"]

    def parts_dir(self):
        if self._parts_dir is None:
            self._parts_dir = os.path.join(self.base_dir(), ".parts")
        return self._parts_dir

    def _ensure_dir(self, path):
        try:
            os.makedirs(path, exist_ok=True)
        except Exception:
            pass

    def get_category_folder(self, filename):
        ext = filename.split(".")[-1].lower() if "." in filename else ""
        if ext in ("mp4", "mkv", "avi", "mov", "webm", "flv", "m4v", "wmv",
                   "mpg", "mpeg", "3gp", "ts"):       return "Video"
        if ext in ("mp3", "wav", "aac", "flac", "m4a", "ogg", "opus", "wma"): return "Music"
        if ext in ("zip", "rar", "7z", "tar", "gz", "bz2", "xz", "tgz", "iso"): return "Compressed"
        if ext in ("pdf", "doc", "docx", "txt", "xlsx", "xls", "pptx", "ppt", "odt", "rtf"): return "Documents"
        if ext in ("exe", "msi", "apk", "deb", "rpm", "dmg", "pkg"):       return "Programs"
        return "General"

    # --- metadata fetching ------------------------------------------------
    def fetch_info(self, url):
        """Return (filename, size) for a URL/plain file. Works offline for
        plain files via HEAD; falls back to yt-dlp for media sites."""
        # 1. yt-dlp for media sites
        if is_media_url(url) and yt_dlp:
            try:
                with yt_dlp.YoutubeDL({"quiet": True, "noplaylist": True}) as ydl:
                    info = ydl.extract_info(url, download=False)
                    title = info.get("title") or f"video_{int(time.time())}"
                    ext = info.get("ext") or "mp4"
                    filename = sanitise_filename(f"{title}.{ext}")
                    size = info.get("filesize") or info.get("filesize_approx") or 0
                    return filename, size
            except Exception:
                pass
        # 2. HEAD request for a raw file
        try:
            req = urllib.request.Request(url, method="HEAD",
                                         headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=10) as resp:
                size = int(resp.getheader("Content-Length", 0) or 0)
                cd = resp.getheader("Content-Disposition", "")
                fname = ""
                if "filename=" in cd:
                    m = re.search(r'filename\*?=([^;]+)', cd, re.I)
                    if m:
                        fname = unquote(m.group(1).strip(' "\''))
                if not fname:
                    fname = os.path.basename(urlparse(url).path)
                if not fname or fname in ("watch", "d", "download"):
                    fname = f"file_{int(time.time())}"
                if not os.path.splitext(fname)[1]:
                    fname += guess_mime_ext(dict(resp.headers.items()), url)
                fname = sanitise_filename(fname)
                return fname, size
        except Exception:
            # No HEAD support: give a sensible default name.
            fname = os.path.basename(urlparse(url).path)
            if not fname or fname in ("watch", "d", "download"):
                fname = f"media_{int(time.time())}.mp4"
            return sanitise_filename(fname), 0

    # --- public task API --------------------------------------------------
    def add_task(self, url, filename=None, size=0, save_path=None,
                 scheduled_at=None, start=True):
        task_id = f"task_{int(time.time()*1000)}_{len(self.tasks)}"
        task = DownloadTask(task_id, url, filename, size, save_path)
        self.tasks[task_id] = task
        task.scheduled_at = scheduled_at
        if scheduled_at is not None and scheduled_at > time.time():
            task.status = "Scheduled"
        else:
            task.status = "Queued"
        self.save_state()
        self._notify(task)
        if start and task.status == "Queued":
            self._try_start(task)
        return task

    def remove_task(self, task_id, delete_parts=True):
        task = self.tasks.pop(task_id, None)
        if not task:
            return
        task.pause_requested = True
        task.cancel_requested = True
        if delete_parts and task.dir:
            self._cleanup_parts(task)
        self.save_state()
        self._notify(task, event="removed")

    def _cleanup_parts(self, task):
        try:
            if task.dir:
                for root, _, files in os.walk(task.dir):
                    for fn in files:
                        if fn.startswith(task.task_id):
                            os.remove(os.path.join(root, fn))
        except Exception:
            pass

    def _part_paths(self, task, n):
        paths = []
        self._ensure_dir(self.parts_dir())
        for i in range(n):
            paths.append(os.path.join(self.parts_dir(),
                                      f"{task.task_id}.part{i}"))
        return paths

    def _existing_parts(self, task):
        files = []
        try:
            for fn in sorted(os.listdir(self.parts_dir())):
                if fn.startswith(task.task_id + ".part"):
                    full = os.path.join(self.parts_dir(), fn)
                    # extract index from ".part<i>"
                    match = re.search(r"\.part(\d+)$", fn)
                    idx = int(match.group(1)) if match else -1
                    files.append((idx, full, os.path.getsize(full)))
        except FileNotFoundError:
            pass
        return files

    # --- control methods --------------------------------------------------
    def pause_task(self, task_id):
        task = self.tasks.get(task_id)
        if not task:
            return
        task.pause_requested = True
        task.cancel_requested = True
        with task.lock:
            if task.status in ("Downloading", "Connecting", "Queued"):
                task.status = "Pausing"
        self._notify(task)

    def resume_task(self, task_id):
        task = self.tasks.get(task_id)
        if not task:
            return
        task.pause_requested = False
        task.cancel_requested = False
        with task.lock:
            if task.status in ("Paused", "Error", "Complete"):
                task.status = "Queued"
        self._notify(task)
        self._try_start(task)

    def stop_all(self):
        for tid in list(self.tasks):
            self.pause_task(tid)

    def resume_all(self):
        for tid in list(self.tasks):
            if self.tasks[tid].status in ("Paused", "Error"):
                self.resume_task(tid)

    def is_active(self, task):
        return task.status in ("Downloading", "Connecting", "Queued")

    def _stop_event(self, task):
        """Return True if the task must stop downloading (pause/cancel)."""
        return task.pause_requested or task.cancel_requested

    # --- progress / throttling -------------------------------------------
    def _on_bytes(self, task, n):
        now = time.time()
        with task.lock:
            task.downloaded += n
            task._samples.append((now, task.downloaded))
            # speed from rolling sample window (>=0.3 s)
            if len(task._samples) >= 2:
                recent = [s for s in task._samples if now - s[0] <= 3]
                if len(recent) >= 2:
                    dt = recent[-1][0] - recent[0][0]
                    db = recent[-1][1] - recent[0][1]
                    if dt > 0:
                        task.speed = db / dt
            if task.size > 0:
                task.eta = (task.size - task.downloaded) / task.speed if task.speed > 0 else 0
                task.percent = task.downloaded / task.size * 100
            else:
                task.eta = 0
            push = (now - task._last_push) >= 0.15 or task.percent >= 100
            if push:
                task._last_push = now
        self._throttle(n)
        if push:
            self._notify(task)

    def _throttle(self, n):
        """Global token-bucket speed limiter (0 = unlimited)."""
        rate = self._bucket_rate
        if rate <= 0:
            return
        with self._buck_lock:
            self._bucket += (time.time() - self._buck_last) * rate
            self._buck_last = time.time()
            if self._bucket > rate * 2:
                self._bucket = rate * 2
            if self._bucket >= n:
                self._bucket -= n
                return
            # want n tokens; not enough -> sleep, then subtract
            missing = n - self._bucket
            time.sleep(missing / rate)
            self._bucket = 0.0
            self._buck_last = time.time()

    def _notify(self, task, event="changed"):
        payload = {
            "event": event,
            "task_id": task.task_id,
            "url": task.url,
            "filename": task.filename,
            "save_path": task.save_path,
            "status": task.status,
            "downloaded": task.downloaded,
            "size": task.size,
            "speed": task.speed,
            "eta": task.eta,
            "percent": task.percent,
            "error": task.error,
            "scheduled_at": task.scheduled_at,
        }
        try:
            self.events.put_nowait(payload)
        except queue_mod.Full:
            pass

    def save_state(self):
        """Persist task states so downloads survive an app restart."""
        state_path = os.path.join(self.base_dir(), ".session.json")
        tasks = []
        for t in self.tasks.values():
            tasks.append({
                "task_id": t.task_id,
                "url": t.url,
                "filename": t.filename,
                "size": t.size,
                "save_path": t.save_path,
                "status": t.status,
                "downloaded": t.downloaded,
                "scheduled_at": t.scheduled_at,
            })
        try:
            self._ensure_dir(self.base_dir())
            with open(state_path, "w", encoding="utf-8") as f:
                json.dump({"options": self.options.data, "tasks": tasks},
                          f, indent=2)
        except Exception:
            pass

    def load_state(self):
        state_path = os.path.join(self.base_dir(), ".session.json")
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for t in data.get("tasks", []):
                task = DownloadTask(t["task_id"], t["url"], t["filename"],
                                    t["size"], t["save_path"])
                task.downloaded = t.get("downloaded", 0)
                task.scheduled_at = t.get("scheduled_at")
                # restore as paused so the user chooses, never auto-flood
                if t.get("status") in ("Downloading", "Queued", "Connecting",
                                       "Pausing", "Idle"):
                    task.status = "Paused"
                    task.pause_requested = True
                elif t.get("status") == "Complete":
                    task.status = "Complete"
                elif t.get("status") == "Error":
                    task.status = "Error"
                else:
                    task.status = "Paused"
                    task.pause_requested = True
                self.tasks[task.task_id] = task
        except (FileNotFoundError, ValueError, KeyError, TypeError):
            return

    # --- the actual download --------------------------------------------
    def start_task(self, task_id):
        task = self.tasks.get(task_id)
        if not task:
            return
        with task.lock:
            if task.status in ("Downloading", "Connecting", "Merging"):
                return
            task.status = "Connecting"
            task.cancel_requested = False
            task.pause_requested = False
            task.error = ""
            task.started_at = time.time()
        self._notify(task)
        threading.Thread(target=self._run, args=(task,), daemon=True).start()

    def _run(self, task):
        """Main worker for one download (handles retry/backoff too)."""
        try:
            self._start_inner(task)
        except Exception as e:
            with task.lock:
                if task.cancel_requested:
                    task.status = "Paused"
                else:
                    task.error = str(e)
                    task.status = "Error"
                    task.retries += 1
                    if task.retries <= self.options.data.get("retries", 3):
                        task.status = "Connecting"
                        time.sleep(min(2 ** task.retries, 30))
                        threading.Thread(target=self._run, args=(task,),
                                         daemon=True).start()
                        self._notify(task)
                        return
                    self._finish(task, error=True)
            self._notify(task)
            self.save_state()

    def _start_inner(self, task):
        with task.lock:
            task.status = "Downloading"
            task.pause_requested = False
            task.cancel_requested = False
            filename = task.filename
        # --- decide destination folder ----------------------------------
        folder = self.get_category_folder(filename)
        self._ensure_dir(os.path.join(self.base_dir(), folder))
        save_path = task.save_path or os.path.join(self.base_dir(), folder, filename)
        task.save_path = save_path
        task.dir = os.path.dirname(save_path)
        self._notify(task)

        # --- media sites via yt-dlp ---------------------------------------
        if is_media_url(task.url) and yt_dlp:
            self._download_media(task)
            if self._stop_event(task) or task.status == "Paused":
                self._notify(task)
                self.save_state()
                return
            self._finish(task)
            return

        # --- raw file: probe size / range support -------------------------
        total, range_ok = self._probe(task.url)
        if not range_ok or total <= 0:
            # fallback to single-stream
            self._download_single(task, self.options.data["speed_limit"])
            self._finish(task)
            return

        with task.lock:
            if task.size <= 0:
                task.size = total
        # resume? existing parts
        parts = self._existing_parts(task)
        has_parts = len(parts) > 0

        segments = self.options.data.get("segments", 6)
        if has_parts:
            # resume segmented: rebuild specs from the parts already on disk
            seg_specs = self._build_segments(task, total, len(parts), parts)
            threads = self._spawn_segments(task, seg_specs)
            self._wait_all(task, threads)
            if task.cancel_requested:
                with task.lock:
                    task.status = "Paused"
                self._notify(task)
                self.save_state()
                return
            self._merge(task)
            self._finish(task)
        else:
            # fresh segmented
            seg_specs = self._build_segments(task, total, segments)
            threads = self._spawn_segments(task, seg_specs)
            self._wait_all(task, threads)
            if task.cancel_requested:
                with task.lock:
                    task.status = "Paused"
                self._notify(task)
                self.save_state()
                return
            self._merge(task)
            self._finish(task)

    def _probe(self, url):
        """Return (total_bytes, range_supported)."""
        try:
            req = urllib.request.Request(url, method="HEAD",
                                         headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=15) as resp:
                total = int(resp.getheader("Content-Length", 0) or 0)
                acc = (resp.getheader("Accept-Ranges") or "").lower()
                range_ok = acc == "bytes"
                # probe with a tiny range request for servers lying about it
                if range_ok and total > 0:
                    try:
                        r = urllib.request.Request(
                            url, headers={"User-Agent": USER_AGENT,
                                          "Range": "bytes=0-0"})
                        with urllib.request.urlopen(r, timeout=15) as rp:
                            range_ok = rp.status == 206
                    except Exception:
                        range_ok = False
                return total, range_ok
        except Exception:
            return 0, False

    def _build_segments(self, task, total, n, existing_parts=None):
        """Return list of (index, start, end, part_path, resume_size)."""
        if n < 1:
            n = 1
        if n > 32:
            n = 32
        n = min(n, total) if total > 0 else 1
        base = total // n
        rem = total % n
        specs = []
        if existing_parts:
            have = {idx: (path, sz) for idx, path, sz in existing_parts}
            cursor = 0
            for i in range(n):
                length = base + (1 if i < rem else 0)
                start = cursor
                end = cursor + length - 1
                cursor += length
                path, sz = have.get(i, ("", 0))
                if not path:
                    path = self._part_paths(task, n)[i]
                specs.append((i, start, end, path, sz))
            return specs
        paths = self._part_paths(task, n)
        cursor = 0
        for i in range(n):
            length = base + (1 if i < rem else 0)
            start = cursor
            end = cursor + length - 1
            cursor += length
            specs.append((i, start, end, paths[i], 0))
        return specs

    def _spawn_segments(self, task, specs):
        threads = []
        with task.lock:
            task._running_threads = 0
        for idx, start, end, path, resume in specs:
            if start > end:
                continue
            th = SegmentThread(self, task, start, end, path, resume,
                               completed_cb=self._seg_done,
                               error_cb=self._seg_error)
            with task.lock:
                task._running_threads += 1
            th.start()
            threads.append(th)
        return threads

    def _seg_done(self, segment):
        with self._state_lock:
            task = segment.task
            with task.lock:
                task._running_threads -= 1
                if task._running_threads == 0 and not task.cancel_requested:
                    # all segments hit the finish line; merging is handled by
                    # the worker thread that called _wait_all, so we only wake
                    # things up here. (No-op is fine — caller waits on threads.)
                    pass
            self._notify(task)

    def _seg_error(self, segment, message):
        with self._state_lock:
            task = segment.task
            if task.cancel_requested:
                return
            with task.lock:
                task.error = message
                task.status = "Error"
                task.pause_requested = True
                task.cancel_requested = True   # stop siblings
            self._notify(task)

    def _wait_all(self, task, threads):
        for th in threads:
            th.join()

    def _merge(self, task):
        """Concatenate the ordered .part files into the final file."""
        with task.lock:
            if task.cancel_requested:
                return
            task.status = "Merging"
        self._notify(task)
        parts = self._existing_parts(task)
        parts.sort(key=lambda p: p[0])
        self._ensure_dir(os.path.dirname(task.save_path))
        tmp = task.save_path + ".idm.tmp"
        try:
            with open(tmp, "wb") as out:
                for idx, path, sz in parts:
                    with open(path, "rb") as src:
                        shutil.copyfileobj(src, out, CHUNK * 16)
            # atomic-ish rename
            if os.path.exists(task.save_path):
                os.remove(task.save_path)
            os.replace(tmp, task.save_path)
            # clean parts
            for _, path, _ in parts:
                try:
                    os.remove(path)
                except Exception:
                    pass
            with task.lock:
                task.downloaded = os.path.getsize(task.save_path)
                task.size = task.downloaded
                task.percent = 100.0
                task.status = "Merged"
        except Exception as e:
            with task.lock:
                task.error = str(e)
            self._notify(task)
            return
        self._notify(task)

    def _finish(self, task, error=False):
        with task.lock:
            task.finished_at = time.time()
            if not error:
                task.status = "Complete"
                task.percent = 100.0
                actual = os.path.getsize(task.save_path) if task.save_path and os.path.exists(task.save_path) else 0
                task.downloaded = max(actual, task.downloaded)
                task.size = task.downloaded or task.size
            else:
                if task.status not in ("Complete",) and not task.cancel_requested:
                    task.status = "Error"
        if task.status == "Complete":
            # tiny delay to ensure the name is right after merge
            self._notify(task, event="completed")
            self._run_queue()   # refill the queue now that a slot is free
        else:
            self._notify(task)
        self.save_state()

    def _download_single(self, task, limit_unused):
        """Old-style single-connection stream with pause/resume & throttle."""
        try:
            existing = os.path.getsize(task.save_path) \
                if task.save_path and os.path.exists(task.save_path) else 0
        except Exception:
            existing = 0
        headers = {"User-Agent": USER_AGENT}
        if existing > 0:
            headers["Range"] = f"bytes={existing}-"
        self._ensure_dir(os.path.dirname(task.save_path) or self.base_dir())
        try:
            req = urllib.request.Request(task.url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                total = int(resp.getheader("Content-Length", 0) or 0)
                if existing > 0 and total > 0:
                    total += existing
                if resp.status == 200 and existing > 0:
                    # server ignored our Range → start over
                    existing = 0
                    total = int(resp.getheader("Content-Length", 0) or 0)
                with task.lock:
                    task.size = total or task.size
                open_mode = "ab" if existing > 0 else "wb"
                with open(task.save_path, open_mode) as f:
                    while True:
                        if self._stop_event(task):
                            break
                        chunk = resp.read(CHUNK)
                        if not chunk:
                            break
                        f.write(chunk)
                        self._on_bytes(task, len(chunk))
            if self._stop_event(task):
                with task.lock:
                    task.status = "Paused"
                self._notify(task)
                self.save_state()
                return
        except Exception as e:
            with task.lock:
                if task.cancel_requested:
                    task.status = "Paused"
                else:
                    task.error = str(e)
                    raise

    def _download_media(self, task):
        """yt-dlp download for media sites with pause/resume + progress."""
        try:
            def hook(d):
                if self._stop_event(task):
                    raise Exception("Paused by user")
                if d["status"] == "downloading":
                    total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                    done = d.get("downloaded_bytes", 0)
                    with task.lock:
                        previous = task.downloaded
                        # give the file a size once known
                        if not task.size:
                            task.size = total
                    delta = done - previous
                    if delta > 0:
                        self._on_bytes(task, delta)
                elif d["status"] == "finished":
                    with task.lock:
                        task.downloaded = task.size
                    self._notify(task)

            outtmpl = os.path.join(task.dir or self.base_dir(),
                                   sanitise_filename(task.filename).rsplit(".", 1)[0] + ".%(ext)s")
            opts = {
                "outtmpl": outtmpl,
                "format": "best",
                "noplaylist": True,
                "quiet": True,
                "nocheckcertificate": True,
                "continuedl": True,
                "progress_hooks": [hook],
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([task.url])
        except Exception as e:
            if str(e) != "Paused by user":
                with task.lock:
                    task.error = str(e)
                    raise
            with task.lock:
                task.status = "Paused"
            self._notify(task)

    # --- queue manager -----------------------------------------------------
    def _try_start(self, task):
        # A queued task is eligible to start now; the queue manager will
        # actually launch it if a concurrency slot is free.
        if task.status not in ("Queued",):
            return
        self._run_queue()

    def _run_queue(self):
        """Kick off queued downloads that fit in the remaining slots."""
        active = self._count_status(("Downloading", "Connecting", "Merging",
                                     "Starting"))
        slots_free = (self.options.data.get("max_concurrent", 3) or 3) - active
        if slots_free <= 0:
            return
        started = 0
        now = time.time()
        for task in sorted(self.tasks.values(),
                           key=lambda t: (0 if t.scheduled_at is None else t.scheduled_at)):
            if started >= slots_free:
                break
            if task.status != "Queued":
                continue
            if task.scheduled_at is not None and task.scheduled_at > now:
                continue  # not time yet
            started += 1
            self.start_task(task.task_id)

    def _count_status(self, statuses):
        c = 0
        for t in self.tasks.values():
            if t.status in statuses:
                c += 1
        return c

    def _on_finish_status(self):
        """Called by UI after processing a completion event to start queued jobs."""
        self._run_queue()

    # --- periodic maintenance (called by the UI timer) --------------------
    def tick(self):
        """Auto-run queued items whose schedule has arrived, and refill slots."""
        now = time.time()
        launch = False
        for task in self.tasks.values():
            if (task.status == "Scheduled" and task.scheduled_at is not None
                    and task.scheduled_at <= now):
                task.status = "Queued"
                launch = True
        if launch or self._count_status(("Queued",)):
            self._run_queue()


# ----------------------------------------------------------------------------
# UI helper widgets
# ----------------------------------------------------------------------------
class StatusBar:
    def __init__(self, parent):
        self.parent = parent
        self.lbl = tk.Label(parent, text="Ready", bg="#252526", fg="#bbb",
                            anchor="w", padx=10)
        self.lbl.pack(side="left", padx=5)
        self.speed_lbl = tk.Label(parent, text="", bg="#252526", fg="#00c8ff",
                                  anchor="e", padx=10)
        self.speed_lbl.pack(side="right", padx=5)
        self.count_lbl = tk.Label(parent, text="", bg="#252526", fg="#ccc",
                                  anchor="e", padx=10)
        self.count_lbl.pack(side="right")

    def set(self, text):
        self.lbl.config(text=text)

    def set_count(self, total, active):
        self.count_lbl.config(text=f"{total} files · {active} active")

    def set_speed(self, bps):
        self.speed_lbl.config(text=f"⬇ {human_rate(bps)}")


# ----------------------------------------------------------------------------
# The Main Window
# ----------------------------------------------------------------------------
class IDMApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} {APP_VERSION}")
        self.geometry("1180x680")
        self.minsize(900, 500)
        self.configure(bg="#1e1e1e")

        # options + engine + event queue
        options_path = os.path.join(os.path.expanduser("~"),
                                    ".infinite_dm_options.json")
        self.options = Options(options_path)
        self.events = queue_mod.Queue()
        self.engine = DownloadEngine(self.options, self.events)
        self.engine.load_state()

        self.tasks = self.engine.tasks
        self.item_counter = 1
        self.current_filter = "All Downloads"
        self.filter_to = {}
        self._clip_watch_job = None
        self._clip_last = None
        self._clip_thread = None
        self._last_finish_time = 0

        self._setup_styles()
        self._setup_ui()
        self._reload()
        self._start_polling()

        # if nothing is restored, classic behavior still fine
        self.after(100, self._poller)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------------------------------------------------------------- styles
    def _setup_styles(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Treeview", background="#252526", foreground="#eee",
                        rowheight=26, fieldbackground="#252526", borderwidth=0)
        style.map("Treeview", background=[("selected", "#007acc")])
        style.configure("Treeview.Heading", background="#333", fg="white",
                       font=("Segoe UI", 9, "bold"))
        style.configure("TProgressbar", troughcolor="#3c3c3c", background="#00c8ff",
                       thickness=14, bordercolor="#3c3c3c", lightcolor="#00c8ff",
                       darkcolor="#00c8ff")

    # ---------------------------------------------------------------- layout
    def _setup_ui(self):
        # Toolbar
        toolbar = tk.Frame(self, bg="#2b2b2b", height=78)
        toolbar.pack(side="top", fill="x")
        btns = [
            ("➕", "New URL", self._add_url),
            ("📋", "Batch", self._batch_add),
            ("▶", "Resume", self._resume_selected),
            ("⏸", "Pause", self._pause_selected),
            ("⏹", "Stop All", self.engine.stop_all),
            ("🗑", "Delete", self._delete_selected),
            ("🧹", "Clear Done", self._delete_completed),
            ("📂", "Open Folder", self._open_folder),
            ("🗂", "Open File", self._open_selected_file),
            ("🕐", "Schedule", self._schedule_selected),
            ("⚙", "Options", self._show_options),
            ("ℹ", "Properties", self._show_properties),
        ]
        for icon, text, cmd in btns:
            tk.Button(toolbar, text=f"{icon}\n{text}", bg="#2b2b2b",
                      fg="#ddd", activebackground="#3c3c3c", activeforeground="white",
                      font=("Segoe UI", 8), relief="flat", bd=0,
                      padx=8, pady=4, cursor="hand2", command=cmd) \
                .pack(side="left", padx=2, pady=6)

        # Main area: sidebar + tree
        main = tk.Frame(self, bg="#1e1e1e")
        main.pack(fill="both", expand=True, padx=6, pady=6)

        sidebar = tk.Frame(main, bg="#252526", width=172)
        sidebar.pack(side="left", fill="y", padx=(0, 6))
        sidebar.pack_propagate(False)
        tk.Label(sidebar, text="Categories", bg="#252526", fg="#ccc",
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(10, 4), padx=12)

        cats = [
            ("All Downloads", "📂"),
            ("Video", "🎬"), ("Music", "🎵"), ("Documents", "📄"),
            ("Compressed", "🗜"), ("Programs", "💿"), ("General", "📁"),
            ("Finished", "✅"), ("Active", "⚡"), ("Scheduled", "🕐"), ("Errors", "❗"),
        ]
        self.filter_buttons = {}
        for cat, icon in cats:
            key = cat
            lbl = tk.Label(sidebar, text=f"{icon} {cat}", bg="#252526",
                           fg="#bbb", font=("Segoe UI", 9), cursor="hand2",
                           anchor="w", padx=8)
            lbl.pack(fill="x", padx=10, pady=2)
            lbl.bind("<Button-1>", lambda e, c=key: self.apply_filter(c))
            self.filter_buttons[key] = lbl

        # Tree
        cols = ("file", "size", "progress", "status", "speed", "eta", "url")
        self.tree = ttk.Treeview(main, columns=cols, show="headings", selectmode="extended")
        heads = [("file", "File Name", 250, "w"),
                 ("size", "Size", 90, "e"),
                 ("progress", "%", 60, "e"),
                 ("status", "Status", 100, "w"),
                 ("speed", "Speed", 90, "e"),
                 ("eta", "ETA", 80, "e"),
                 ("url", "URL", 260, "w")]
        for col, txt, w, anc in heads:
            self.tree.heading(col, text=txt)
            self.tree.column(col, width=w, anchor=anc)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb = ttk.Scrollbar(main, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda e: self._open_selected_file())
        self.tree.bind("<Delete>", lambda e: self._delete_selected())

        # Status bar
        statusbar = tk.Frame(self, bg="#252526", height=26)
        statusbar.pack(side="bottom", fill="x")
        self.statusbar = StatusBar(statusbar)

    # ------------------------------------------------------------ tree ops
    def _insert_or_update(self, payload):
        tid = payload.get("task_id", "")
        if not tid:
            return
        if not self.tree.exists(tid):
            fname = payload.get("filename", tid)
            self.tree.insert("", "end", iid=tid,
                             values=(fname, "unknown", "0",
                                     payload.get("status", "…"), "-", "-",
                                     payload.get("url", "")))
        vals = list(self.tree.item(tid, "values"))
        status = payload.get("status")
        if status:
            vals[3] = status
        size_total = payload.get("size", 0) or 0
        vals[1] = human_size(size_total) if size_total > 0 else "unknown"
        pct = payload.get("percent", 0) or 0
        if pct:
            vals[2] = f"{pct:.1f}%"
        speed = payload.get("speed", 0) or 0
        vals[4] = human_rate(speed)
        eta = payload.get("eta", 0) or 0
        vals[5] = str(timedelta(seconds=int(eta))) if eta > 0 else "-"
        url = payload.get("url")
        if url:
            vals[6] = url
        self.tree.item(tid, values=vals)

    # -------------------------------------------------------------- filter
    def apply_filter(self, category):
        self.current_filter = category
        for btn in self.filter_buttons.values():
            btn.configure(fg="#bbb")
        if category in self.filter_buttons:
            self.filter_buttons[category].configure(fg="#00c8ff")
        for item in self.tree.get_children():
            self.tree.detach(item)
        to_show = []
        for tid, task in self.tasks.items():
            if self._task_matches(tid, task, category):
                to_show.append(tid)
        for tid in to_show:
            if self.tree.exists(tid):
                self.tree.reattach(tid, "", "end")

    def _task_matches(self, tid, task, category):
        stats = task.status
        if category == "All Downloads":
            return True
        if category == "Finished":
            return stats == "Complete"
        if category == "Active":
            return stats in ("Downloading", "Connecting", "Merging",
                             "Queued", "Scheduled", "Pausing")
        if category == "Scheduled":
            return stats == "Scheduled"
        if category == "Errors":
            return stats == "Error" or (task.error and stats != "Complete")
        return self.engine.get_category_folder(task.filename) == category

    # ------------------------------------------------------------ dialogs
    def _add_url(self):
        url = simpledialog.askstring("Add URL", "Enter download URL:",
                                     parent=self)
        if url and url.strip():
            self._finish_parse_url(url.strip())

    def _batch_add(self):
        win = tk.Toplevel(self)
        win.title("Batch Add — paste one URL per line")
        win.geometry("500x400")
        win.configure(bg="#252526")
        tk.Label(win, text="Paste URLs (one per line):", bg="#252526",
                 fg="white", font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=12, pady=(12, 4))
        txt = tk.Text(win, bg="#1e1e1e", fg="#ddd", insertbackground="white",
                      relief="flat", font=("Consolas", 10))
        txt.pack(fill="both", expand=True, padx=12, pady=4)

        def go():
            urls = [ln.strip() for ln in txt.get("1.0", "end").splitlines() if is_url(ln)]
            win.destroy()
            self._parse_and_add(urls[0]) if len(urls) == 1 else self._start_batch(urls)

        tk.Button(win, text="Start Downloads", bg="#007acc", fg="white",
                  font=("Segoe UI", 10, "bold"), relief="flat", padx=16, pady=6,
                  command=go).pack(pady=10)

    def _parse_and_add(self, url):
        """Fetch info and show the pre-download dialog; then start."""
        try:
            self.statusbar.set(f"Fetching info for {url[:60]}…")
            fname, size = self.engine.fetch_info(url)
        except Exception:
            fname, size = os.path.basename(urlparse(url).path) or f"file_{int(time.time())}", 0
        self._show_predownload_dialog(url, fname, size, None)

    def _start_batch(self, urls):
        count = 0
        for i, url in enumerate(urls):
            self.statusbar.set(f"Preparing batch… ({i}/{len(urls)})")
            try:
                fname, size = self.engine.fetch_info(url)
                self.engine.add_task(url, filename=fname, size=size,
                                     start=True)
            except Exception:
                # if fetching info fails, still queue with a generic name
                try:
                    self.engine.add_task(url, filename=f"file_{int(time.time())}.bin",
                                         size=0, start=True)
                except Exception:
                    continue
            count += 1
        self.statusbar.set(f"Added {count} downloads to queue.")

    # ------------------------------------------------------------------
    def _show_predownload_dialog(self, url, fname, size, extra, auto=False):
        dlg = tk.Toplevel(self)
        dlg.title("Download File Info — " + (fname[:40] if len(fname) > 40 else fname))
        dlg.geometry("620x340")
        dlg.configure(bg="#252526")
        dlg.resizable(False, False)

        url_frame = tk.Frame(dlg, bg="#252526")
        url_frame.pack(fill="x", padx=16, pady=(22, 8))
        tk.Label(url_frame, text="URL:", bg="#252526", fg="white",
                 width=8, anchor="w").pack(side="left")
        url_entry = tk.Entry(url_frame, bg="#1e1e1e", fg="#aaa", relief="flat", insertbackground="white")
        url_entry.insert(0, url)
        url_entry.config(state="readonly")
        url_entry.pack(side="left", fill="x", expand=True)

        name_frame = tk.Frame(dlg, bg="#252526")
        name_frame.pack(fill="x", padx=16, pady=8)
        tk.Label(name_frame, text="File name:", bg="#252526", fg="white",
                 width=8, anchor="w").pack(side="left")
        name_field = tk.Entry(name_frame, bg="#1e1e1e", fg="white",
                              insertbackground="white", relief="flat")
        name_field.insert(0, fname)
        name_field.pack(side="left", fill="x", expand=True)

        path_frame = tk.Frame(dlg, bg="#252526")
        path_frame.pack(fill="x", padx=16, pady=8)
        tk.Label(path_frame, text="Save to:", bg="#252526", fg="white",
                 width=8, anchor="w").pack(side="left")
        path_field = tk.Entry(path_frame, bg="#1e1e1e", fg="white",
                              insertbackground="white", relief="flat")
        default_path = os.path.join(self.options.data["download_dir"],
                                    self.engine.get_category_folder(fname), fname)
        path_field.insert(0, default_path)
        path_field.pack(side="left", fill="x", expand=True, padx=(0, 6))
        tk.Button(path_frame, text="Browse…", bg="#3c3c3c", fg="white",
                  relief="flat", command=lambda: self._browse_path(path_field)) \
            .pack(side="right")

        info_frame = tk.Frame(dlg, bg="#252526")
        info_frame.pack(fill="x", padx=16, pady=4)
        tk.Label(info_frame, text=f"File size: {human_size(size) if size else 'unknown (will be detected)'}",
                 bg="#252526", fg="#ccc", font=("Segoe UI", 9)).pack(anchor="w")

        def do_start():
            name = sanitise_filename(name_field.get().strip()) or f"file_{int(time.time())}"
            path = path_field.get().strip()
            if not path:
                path = os.path.join(self.options.data["download_dir"],
                                    self.engine.get_category_folder(name), name)
            if os.path.isdir(path) or not os.path.splitext(path)[1]:
                try:
                    os.makedirs(path, exist_ok=True)
                except Exception:
                    pass
                path = os.path.join(path, name)
            dlg.destroy()
            task = self.engine.add_task(url, filename=name, size=size,
                                        save_path=path, start=True)
            self.statusbar.set(f"Queued: {name}")

        tk.Button(dlg, text="Start Download", bg="#0a84ff", fg="white",
                  font=("Segoe UI", 10, "bold"), relief="flat", padx=18, pady=6,
                  command=do_start).pack(pady=16)

    def _browse_path(self, entry):
        d = filedialog.askdirectory(parent=self, title="Choose download folder")
        if d:
            entry.delete(0, "end")
            entry.insert(0, d)

    # ------------------------------------------------------------ actions
    def _selected_ids(self):
        return self.tree.selection()

    def _pause_selected(self):
        for tid in self._selected_ids():
            self.engine.pause_task(tid)
        self._refresh_statusbar()

    def _resume_selected(self):
        for tid in self._selected_ids():
            self.engine.resume_task(tid)
        self._refresh_statusbar()

    def _delete_selected(self):
        ids = list(self._selected_ids())
        if not ids:
            return
        for tid in ids:
            self.engine.remove_task(tid)
            if self.tree.exists(tid):
                self.tree.delete(tid)
        self._refresh_statusbar()

    def _delete_completed(self):
        removed = False
        for tid in list(self.tasks.keys()):
            if self.tasks[tid].status == "Complete":
                self.engine.remove_task(tid)
                if self.tree.exists(tid):
                    self.tree.delete(tid)
                removed = True
        if removed:
            self._refresh_statusbar()

    def _open_folder(self):
        # If a task is selected, open its folder; otherwise the base dir.
        sel = self._selected_ids()
        path = self.options.data["download_dir"]
        if sel:
            task = self.tasks.get(sel[0])
            if task and task.save_path:
                path = os.path.dirname(task.save_path)
        self._open_in_explorer(path)

    def _open_selected_file(self):
        sel = self._selected_ids()
        if not sel:
            return
        task = self.tasks.get(sel[0])
        if not task or not task.save_path:
            messagebox.showinfo("Open File",
                                "This download has not finished yet.", parent=self)
            return
        if not os.path.exists(task.save_path):
            messagebox.showwarning("Open File",
                                   "File not found on disk.", parent=self)
            return
        self._launch_file(task.save_path)

    @staticmethod
    def _open_in_explorer(path):
        if not os.path.exists(path):
            path = os.path.dirname(path) or "."
        if os.name == "nt":
            try:
                os.startfile(os.path.normpath(path))  # noqa: B016
                return
            except Exception:
                pass
        for cmd in (["xdg-open", path], ["open", path], ["gio", "open", path]):
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
                return
            except Exception:
                continue

    @staticmethod
    def _launch_file(path):
        if os.name == "nt":
            try:
                os.startfile(path)  # noqa: B016
                return
            except Exception:
                messagebox.showerror("Open File", "Could not open the file.")
                return
        for cmd in (["xdg-open", path], ["open", path]):
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
                return
            except Exception:
                continue
        messagebox.showerror("Open File", "Could not open the file.")

    def _schedule_selected(self):
        sel = self._selected_ids()
        if not sel:
            return
        task = self.tasks.get(sel[0])
        if not task:
            return
        ans = simpledialog.askstring(
            "Schedule Download",
            "Start at (YYYY-MM-DD HH:MM), or leave empty to remove schedule:",
            initialvalue=datetime.now().strftime("%Y-%m-%d %H:%M"),
            parent=self)
        if ans is None:
            return
        ans = ans.strip()
        if not ans:
            task.scheduled_at = None
            task.status = "Paused"
            self.engine._notify(task)
            self.statusbar.set("Schedule removed.")
            return
        try:
            dt = datetime.strptime(ans, "%Y-%m-%d %H:%M")
            task.scheduled_at = dt.timestamp()
            task.status = "Scheduled"
            self.engine.save_state()
            self.engine._notify(task)
            self.statusbar.set(f"Scheduled for {dt.strftime('%d %b %Y %H:%M')}")
        except ValueError:
            messagebox.showerror("Schedule", "Use format YYYY-MM-DD HH:MM",
                                 parent=self)

    def _show_options(self):
        win = tk.Toplevel(self)
        win.title("Options")
        win.geometry("460x470")
        win.configure(bg="#252526")
        win.resizable(False, False)

        # download dir
        f0 = tk.Frame(win, bg="#252526")
        f0.pack(fill="x", padx=18, pady=(18, 6))
        tk.Label(f0, text="Download folder:", bg="#252526", fg="white",
                 width=18, anchor="w").pack(side="left")
        dir_var = tk.StringVar(value=self.options.data["download_dir"])
        tk.Entry(f0, textvariable=dir_var, bg="#1e1e1e", fg="white",
                 insertbackground="white", relief="flat").pack(side="left", fill="x", expand=True, padx=(0, 6))
        tk.Button(f0, text="…", bg="#3c3c3c", fg="white", relief="flat",
                  command=lambda: dir_var.set(filedialog.askdirectory(parent=win) or dir_var.get())) \
            .pack(side="right")

        def row(parent, i, label, var, from_, to):
            fr = tk.Frame(parent, bg="#252526")
            fr.pack(fill="x", padx=18, pady=6)
            tk.Label(fr, text=label, bg="#252526", fg="white",
                     width=18, anchor="w").pack(side="left")
            tk.Spinbox(fr, from_=from_, to=to, textvariable=var,
                       bg="#1e1e1e", fg="white", buttonbackground="#3c3c3c",
                       relief="flat", width=8).pack(side="left")

        seg_var = tk.IntVar(value=self.options.data["segments"])
        conc_var = tk.IntVar(value=self.options.data["max_concurrent"])
        speed_var = tk.IntVar(value=int(self.options.data["speed_limit"] / 1024))
        retry_var = tk.IntVar(value=self.options.data["retries"])
        clip_var = tk.BooleanVar(value=self.options.data["clipboard_monitor"])

        row(win, 0, "Connections (per file):", seg_var, 1, 32)
        row(win, 1, "Max simultaneous:", conc_var, 1, 16)
        row(win, 2, "Speed limit (KB/s, 0 off):", speed_var, 0, 1000000)
        row(win, 3, "Auto retries:", retry_var, 0, 20)

        tk.Checkbutton(win, text="Monitor clipboard for links",
                       variable=clip_var, bg="#252526", fg="white",
                       activebackground="#252526", activeforeground="white",
                       bd=0, anchor="w").pack(fill="x", padx=18, pady=4)

        def save():
            self.options.data.update({
                "segments": max(1, seg_var.get()),
                "max_concurrent": max(1, conc_var.get()),
                "speed_limit": max(0, speed_var.get() * 1024),
                "retries": max(0, retry_var.get()),
                "clipboard_monitor": clip_var.get(),
                "download_dir": dir_var.get().strip(),
            })
            self.engine._bucket_rate = self.options.data["speed_limit"]
            self.options.save()
            win.destroy()
            self.statusbar.set("Options saved.")
            self._reload()  # saved folder filters
            self._start_clipboard_maybe()

        tk.Button(win, text="Save", bg="#0a84ff", fg="white",
                  padx=22, pady=5, relief="flat", font=("Segoe UI", 10, "bold"),
                  command=save).pack(pady=14)

    def _show_properties(self):
        sel = self._selected_ids()
        if not sel:
            return
        task = self.tasks.get(sel[0])
        if not task:
            return
        prop = tk.Toplevel(self)
        prop.title("Download Properties")
        prop.geometry("520x300")
        prop.configure(bg="#f0f0f0")
        rows = [
            ("File name:", task.filename),
            ("URL:", task.url),
            ("Status:", task.status),
            ("Size:", human_size(task.size)),
            ("Downloaded:", human_size(task.downloaded)),
            ("Speed:", human_rate(task.speed)),
            ("Start:", datetime.fromtimestamp(task.started_at).strftime("%Y-%m-%d %H:%M:%S")
                   if task.started_at else "-"),
            ("Path:", task.save_path or "-"),
            ("Error:", task.error or "none"),
        ]
        for label, value in rows:
            tk.Label(prop, text=f"{label} {value}", anchor="w",
                     font=("Segoe UI", 9, "bold") if label == "File name:" else ("Segoe UI", 9),
                     fg="#333", wraplength=480).pack(fill="x", padx=20, pady=3)
        tk.Button(prop, text="OK", command=prop.destroy, width=10,
                  bg="#0a84ff", fg="white", relief="flat").pack(pady=6)

    # ------------------------------------------------------- event polling
    def _start_polling(self):
        self._start_clipboard_maybe()

    def _start_clipboard_maybe(self):
        if not self.options.data.get("clipboard_monitor", True):
            self._clip_thread = None
            return
        if self._clip_thread and self._clip_thread.is_alive():
            return
        self._clip_thread = threading.Thread(target=self._clip_loop,
                                             daemon=True)
        self._clip_thread.start()

    def _clip_loop(self):
        if pyperclip is None:
            return
        last = self._clip_last
        while True:
            try:
                text = pyperclip.paste()
            except Exception:
                text = None
            if text and text != last and is_url_like(text):
                m = re.search(r"https?://[^\s\"'<>]+", text)
                if m:
                    url = m.group(0)
                    known = {t.url for t in self.tasks.values()}
                    if url not in known and not self._clip_prompt_shown(url):
                        self.events.put_nowait({"event": "clipboard",
                                                "url": url})
                        last = text
            time.sleep(1.8)

    def _clip_prompt_shown(self, url):
        # lightweight guard against re-prompting the same URL too often
        now = time.time()
        key = url
        cache = getattr(self, "_clip_seen", {})
        if key in cache and now - cache[key] < 30:
            return True
        cache[key] = now
        self._clip_seen = cache
        return False

    # -------------------------------------------------------------- poller
    def _poller(self):
        while True:
            try:
                payload = self.events.get_nowait()
            except queue_mod.Empty:
                break
            try:
                self._handle_event(payload)
            except Exception as e:
                print("Event error:", e)
        # periodic engine maintenance (schedules, queue refill)
        try:
            self.engine.tick()
        except Exception:
            pass
        self.after(120, self._poller)

    def _handle_event(self, payload):
        kind = payload.get("event", "changed")
        tid = payload.get("task_id", "")
        if kind == "removed":
            return
        if kind == "clipboard":
            self._offer_clipboard_url(payload["url"])
            return
        if tid and self.tree.exists(tid):
            self._insert_or_update(payload)
        elif tid:
            # new task row
            self._insert_or_update(payload)
        self._refresh_statusbar()
        self.apply_filter(self.current_filter)
        if kind == "completed":
            self._notify_complete(payload)

    def _refresh_statusbar(self):
        total = len(self.tasks)
        active = sum(1 for t in self.tasks.values()
                     if t.status in ("Downloading", "Connecting", "Merging"))
        speed = sum(t.speed for t in self.tasks.values())
        self.statusbar.set_count(total, active)
        self.statusbar.set_speed(speed)
        self.statusbar.set(f"{self.current_filter} — {total} files")

    def _notify_complete(self, payload):
        # audible + visual notification when a download finishes
        try:
            self.bell()
        except Exception:
            pass
        try:
            if os.name == "nt":
                import winsound
                winsound.MessageBeep()
        except Exception:
            pass
        if not self.focused or not self.winfo_viewable():
            self.title(f"✔ {payload.get('filename', '')} — {APP_NAME}")
            self.after(3000, lambda: self.title(f"{APP_NAME} {APP_VERSION}"))

    def _offer_clipboard_url(self, url):
        self._auto_add_win = None
        self.attributes("-topmost", True)
        ans = messagebox.askyesno(
            "Clipboard link detected",
            f"Download this URL?\n\n{url[:120]}",
            parent=self)
        self.attributes("-topmost", False)
        if ans:
            try:
                self._parse_and_add(url)
            except Exception:
                pass

    # ------------------------------------------------------------- misc
    def _reload(self):
        """Re-apply category filter and refresh tree from current tasks."""
        for tid, task in self.tasks.items():
            if not self.tree.exists(tid):
                self.tree.insert("", "end", iid=tid,
                                 values=(task.filename,
                                         human_size(task.size) or "unknown",
                                         f"{task.percent:.1f}%" if task.percent else "0",
                                         task.status, "-", "-",
                                         task.url or ""))
            else:
                self._insert_or_update({
                    "task_id": tid, "url": task.url, "filename": task.filename,
                    "save_path": task.save_path, "status": task.status,
                    "downloaded": task.downloaded, "size": task.size,
                    "speed": task.speed, "eta": task.eta, "percent": task.percent,
                })
        self.apply_filter(self.current_filter)
        self._refresh_statusbar()

    def _on_close(self):
        # stop anything still running, save state, and quit
        self.engine.stop_all()
        self.engine.save_state()
        self.destroy()


# ----------------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------------
def url_is_http(u):
    return bool(is_url(u))


def is_url_like(u):
    return bool(re.match(r"^https?://", (u or "").strip(), re.I))


def main():
    app = IDMApp()
    app.mainloop()


if __name__ == "__main__":
    main()

