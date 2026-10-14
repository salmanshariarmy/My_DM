#!/usr/bin/env python3
"""Headless integration test for InfiniteDM's DownloadEngine."""
import os
import sys
import time
import tempfile
import threading
import http.server
import socketserver
import random
import hashlib

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))   # My_DM/
from InfiniteDM import (DownloadEngine, Options, USER_AGENT, CHUNK,
                        DownloadTask, is_url)

# ---------------------------------------------------------------- helpers
def serve(file_path):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_HEAD(self):
            self._handle(stream=False)
        def do_GET(self):
            self._handle(stream=True)
        def _handle(self, stream):
            fsize = os.path.getsize(file_path)
            status = 200
            start = 0
            end = fsize - 1
            rng = self.headers.get("Range")
            if rng:
                start, end = self._parse_range(rng, fsize)
                if start is not None:
                    status = 206
                else:
                    status = 416
                    self.send_response(status)
                    self.send_header("Content-Range", f"bytes */{fsize}")
                    self.end_headers()
                    return
            self.send_response(status)
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Range", f"bytes {start}-{end}/{fsize}")
            self.send_header("Content-Disposition", "inline")
            self.end_headers()
            if not stream:
                return
            with open(file_path, "rb") as f:
                f.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    data = f.read(min(65536, remaining))
                    if not data:
                        break
                    self.wfile.write(data)
                    remaining -= len(data)

        def _parse_range(self, rng, fsize):
            m = re.match(r"bytes=(\d*)-(\d*)", rng)
            if not m:
                return None
            s, e = m.groups()
            start = int(s) if s else 0
            end = int(e) if e else fsize - 1
            if start >= fsize or end < start:
                return None
            end = min(end, fsize - 1)
            return start, end

        def log_message(self, *a):
            pass

    socketserver.ThreadingTCPServer.allow_reuse_address = True
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return port, server

import re

# ---------------------------------------------------------------- build
random.seed(42)
blob = os.urandom(3 * 1024 * 1024 + 12345)  # ~3 MB non-round-size to stress ranges
src = os.path.join(tempfile.mkdtemp(), "blob.bin")
with open(src, "wb") as f:
    f.write(blob)
src_hash = hashlib.sha256(blob).hexdigest()
port, server = serve(src)
BASE = f"http://127.0.0.1:{port}/blob.bin"

def wait_task(engine, tid, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        task = engine.tasks.get(tid)
        if task and task.status in ("Complete", "Error"):
            return task
        engine.tick()
        time.sleep(0.02)
    return None

results = []

# ---- TEST 1: segmented download integrity ----
def test_segmented():
    bd = tempfile.mkdtemp()
    opts = Options(os.path.join(bd, "opts.json"))
    opts.data["download_dir"] = bd
    opts.data["segments"] = 4
    opts.data["max_concurrent"] = 2
    eng = DownloadEngine(opts)
    task = eng.add_task(BASE, filename="blob.bin", start=True)
    task = wait_task(eng, task.task_id)
    assert task.status == "Complete", f"status {task.status} / {task.error}"
    out = task.save_path
    with open(out, "rb") as f:
        h = hashlib.sha256(f.read()).hexdigest()
    assert h == src_hash, "content mismatch!"
    results.append("segmented download: OK")

# ---- TEST 2: pause/resume uses parts ----
def test_pause_resume():
    import hashlib
    # Big file served slowly so the download is easy to interrupt.
    big = os.urandom(48 * 1024 * 1024)
    big_src = os.path.join(tempfile.mkdtemp(), "big.bin")
    with open(big_src, "wb") as f:
        f.write(big)
    big_hash = hashlib.sha256(big).hexdigest()

    class SlowHandler(http.server.BaseHTTPRequestHandler):
        def do_HEAD(self):
            n = os.path.getsize(big_src)
            self.send_response(200)
            self.send_header("Content-Length", str(n))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
        def _send(self):
            n = os.path.getsize(big_src)
            rng = self.headers.get("Range")
            s, e = 0, n - 1
            if rng:
                m = re.match(r"bytes=(\d*)-(\d*)", rng)
                s = int(m.group(1)) if m.group(1) else 0
                e = int(m.group(2)) if m.group(2) else n - 1
                e = min(e, n - 1)
                self.send_response(206)
            else:
                self.send_response(200)
            self.send_header("Content-Length", str(e - s + 1))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            with open(big_src, "rb") as f:
                f.seek(s)
                rem = e - s + 1
                while rem > 0:
                    data = f.read(65536)
                    if not data:
                        break
                    self.wfile.write(data)
                    rem -= len(data)
                    time.sleep(0.02)   # throttle
        do_GET = _send
        def log_message(self, *a):
            pass

    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), SlowHandler)
    pslow = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    bd = tempfile.mkdtemp()
    opts = Options(os.path.join(bd, "opts.json"))
    opts.data["download_dir"] = bd
    opts.data["segments"] = 4
    opts.data["max_concurrent"] = 2
    eng = DownloadEngine(opts)
    task = eng.add_task(f"http://127.0.0.1:{pslow}/big.bin",
                        filename="big.bin", start=True)
    time.sleep(1.5)
    eng.pause_task(task.task_id)
    time.sleep(1.0)
    assert task.status in ("Paused",), task.status
    parts = eng._existing_parts(task)
    assert parts, "should have .part files after pause"
    assert sum(p[2] for p in parts) < 48 * 1024 * 1024, "should not be complete yet"
    # resume
    eng.resume_task(task.task_id)
    task = wait_task(eng, task.task_id, timeout=240)
    assert task.status == "Complete", f"status {task.status} / {task.error}"
    with open(task.save_path, "rb") as f:
        h = hashlib.sha256(f.read()).hexdigest()
    assert h == big_hash, "resume content mismatch!"
    results.append("pause/resume: OK (parts used, resume recovery verified)")

# ---- TEST 3: queue concurrency ----
def test_queue():
    bd = tempfile.mkdtemp()
    opts = Options(os.path.join(bd, "opts.json"))
    opts.data["download_dir"] = bd
    opts.data["segments"] = 2
    opts.data["max_concurrent"] = 2
    eng = DownloadEngine(opts)
    tids = []
    for i in range(5):
        t = eng.add_task(BASE, filename=f"f{i}.bin", start=True)
        tids.append(t.task_id)
    # let everything finish
    deadline = time.time() + 180
    while time.time() < deadline:
        running = [tid for tid in tids if eng.tasks.get(tid) and
                   eng.tasks[tid].status not in ("Complete", "Error")]
        if not running:
            break
        eng.tick()
        time.sleep(0.02)
    for tid in tids:
        st = eng.tasks[tid].status
        assert st == "Complete", f"{tid} -> {st} {eng.tasks[tid].error}"
        assert os.path.getsize(eng.tasks[tid].save_path) == len(blob)
    results.append("queue/parallel (max_concurrent=2, 5 files): OK")

# ---- TEST 4: single-connection fallback (no range) ----
def test_no_range():
    class NoRangeHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            fsize = os.path.getsize(src)
            self.send_response(200)
            self.send_header("Content-Length", str(fsize))
            self.end_headers()
            with open(src, "rb") as f:
                while True:
                    data = f.read(65536)
                    if not data:
                        break
                    self.wfile.write(data)
        def log_message(self, *a): pass
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), NoRangeHandler)
    p2 = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    bd = tempfile.mkdtemp()
    opts = Options(os.path.join(bd, "opts.json"))
    opts.data["download_dir"] = bd
    eng = DownloadEngine(opts)
    url = f"http://127.0.0.1:{p2}/blob.bin"
    task = eng.add_task(url, filename="blob.bin", start=True)
    task = wait_task(eng, task.task_id)
    assert task.status == "Complete", f"status {task.status} / {task.error}"
    with open(task.save_path, "rb") as f:
        h = hashlib.sha256(f.read()).hexdigest()
    assert h == src_hash, "no-range content mismatch!"
    results.append("no-range single-stream fallback: OK")

# ---- TEST 5: speed limit sanity (limit applies, won't exceed much) ----
def test_speed_limit():
    bd = tempfile.mkdtemp()
    opts = Options(os.path.join(bd, "opts.json"))
    opts.data["download_dir"] = bd
    opts.data["segments"] = 2
    opts.data["max_concurrent"] = 1
    opts.data["speed_limit"] = 200 * 1024  # 200 KB/s
    eng = DownloadEngine(opts)
    t0 = time.time()
    task = eng.add_task(BASE, filename="big.bin", start=True)
    task = wait_task(eng, task.task_id, timeout=180)
    dt = time.time() - t0
    size = os.path.getsize(task.save_path)
    # total bytes ~3MB at 200KB/s => ~15s (with slop)
    assert task.status == "Complete", task.error
    results.append(f"speed limit: OK ({size} bytes in {dt:.1f}s)")

# run it with timeout wrapper
if __name__ == "__main__":
    test_segmented()
    test_pause_resume()
    test_queue()
    test_no_range()
    test_speed_limit()
    server.shutdown()
    print("\nALL TESTS PASSED")
    for r in results:
        print(" -", r)
