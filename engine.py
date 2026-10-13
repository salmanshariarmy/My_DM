import os
import time
import urllib.request
from urllib.parse import unquote, urlparse
import yt_dlp
import re
import threading

class DownloadEngine:
    def __init__(self, download_dir):
        self.download_dir = download_dir
        self.cancel_flag = False

    def get_file_info(self, url):
        # Fetch initial info like size and filename (Like IDM's pre-download info)
        try:
            req = urllib.request.Request(url, method='HEAD', headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=5) as response:
                size = int(response.getheader('Content-Length', 0))
                cd = response.getheader('Content-Disposition')
                filename = ""
                if cd and 'filename=' in cd:
                    filename = unquote(cd.split('filename=')[1].split(';')[0].strip(' "\''))
                if not filename:
                    filename = os.path.basename(urlparse(url).path)
                if not filename: filename = f"file_{int(time.time())}.dat"
                return re.sub(r'[\\/*?:"<>|]', "", filename), size
        except:
            return f"video_{int(time.time())}.mp4", 0 # Fallback for yt-dlp

    def download_direct(self, url, filename, progress_callback):
        self.cancel_flag = False
        filepath = os.path.join(self.download_dir, filename)
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        
        try:
            with urllib.request.urlopen(req) as response:
                total_size = int(response.getheader('Content-Length', 0))
                downloaded = 0
                start_time = time.time()
                
                with open(filepath, 'wb') as f:
                    while True:
                        if self.cancel_flag: raise Exception("Paused")
                        chunk = response.read(65536)
                        if not chunk: break
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        # Update UI
                        now = time.time()
                        elapsed = now - start_time
                        speed = downloaded / elapsed if elapsed > 0 else 0
                        progress_callback(downloaded, total_size, speed)
        except Exception as e:
            if str(e) != "Paused": raise e
