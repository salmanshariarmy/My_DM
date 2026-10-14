#!/usr/bin/env python3
"""Smoke-test the InfiniteDM GUI under Xvfb: build the window, add a task,
pump the Tk event loop, then destroy it. (No real display needed.)"""
import os
import sys
import time
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import InfiniteDM
from InfiniteDM import IDMApp, DownloadEngine, Options

def main():
    # Point the app at a temp download dir so we don't touch the real home.
    tmp = tempfile.mkdtemp()

    # Build the app but override options path to temp so nothing writes home.
    import InfiniteDM as M
    app = M.IDMApp()
    app.options.data["download_dir"] = os.path.join(tmp, "My_IDM_Downloads")
    app.options.data["clipboard_monitor"] = False
    app.update()

    # Simulate adding a URL task directly through the engine (statusbar works)
    app.engine.add_task("http://invalid.invalid/file.zip", filename="demo.zip",
                        size=12345, start=False)
    app.update()
    # pump several event loops to ensure poller/tree updates don't crash
    for _ in range(20):
        app.update()
        time.sleep(0.01)

    # Trigger the filter/tree refresh code paths
    app.apply_filter("All Downloads")
    app._refresh_statusbar()
    app.update()

    # Test that removing works
    tid = list(app.engine.tasks)[0]
    app.engine.remove_task(tid)
    app.update()

    # Schedule dialog path (bypass actual dialog; set directly)
    task = app.engine.add_task("http://example.com/a.pdf", filename="a.pdf",
                               size=100, start=False)
    task.scheduled_at = time.time() - 10
    task.status = "Scheduled"
    app.engine.tick()   # should flip Scheduled -> Queued and try to run
    app.update()

    print("UI SMOKE TEST OK, tasks:", len(app.engine.tasks))
    app.destroy()

if __name__ == "__main__":
    main()
