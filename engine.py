import os
import time
import threading
import urllib.request
from urllib.parse import unquote, urlparse
import yt_dlp
import re

class DownloadEngine:
    def __init__(self, base_dir):
        self.base_dir = base_dir
        self.active_downloads = {} # Tracks active threads and flags

    def get_category_folder(self, filename):
        ext = filename.split('.')[-1].lower() if '.' in filename else ''
        if ext in ['mp4', 'mkv', 'avi', 'mov', 'webm']: return "Video"
        elif ext in ['mp3', 'wav', 'aac', 'flac']: return "Music"
        elif ext in ['zip', 'rar', '7z', 'tar', 'gz']: return "Compressed"
        elif ext in ['pdf', 'doc', 'docx', 'txt', 'xlsx']: return "Documents"
        elif ext in ['exe', 'msi', 'apk']: return "Programs"
        return "General"

    def fetch_info(self, url):
        try:
            req = urllib.request.Request(url, method='HEAD', headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=5) as resp:
                size = int(resp.getheader('Content-Length', 0))
                cd = resp.getheader('Content-Disposition')
                fname = ""
                if cd and 'filename=' in cd:
                    fname = unquote(cd.split('filename=')[1].split(';')[0].strip(' "\''))
                if not fname: fname = os.path.basename(urlparse(url).path)
                if not fname: fname = f"download_{int(time.time())}.dat"
                fname = re.sub(r'[\\/*?:"<>|]', "", fname)
                return fname, size
        except:
            return f"media_{int(time.time())}.mp4", 0

    def start_download(self, item_id, url, filename, progress_callback, finish_callback, error_callback):
        self.active_downloads[item_id] = {'cancel': False}
        
        category = self.get_category_folder(filename)
        save_dir = os.path.join(self.base_dir, category)
        os.makedirs(save_dir, exist_ok=True)
        filepath = os.path.join(save_dir, filename)

        def download_thread():
            try:
                existing_size = os.path.getsize(filepath) if os.path.exists(filepath) else 0
                headers = {'User-Agent': 'Mozilla/5.0'}
                open_mode = 'wb'
                
                # Setup Resume (Range header)
                if existing_size > 0:
                    headers['Range'] = f'bytes={existing_size}-'
                    open_mode = 'ab'

                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req) as resp:
                    total_size = int(resp.getheader('Content-Length', 0)) + existing_size
                    if existing_size >= total_size and total_size > 0:
                        finish_callback(item_id, filepath)
                        return

                    downloaded = existing_size
                    start_time = time.time()
                    
                    with open(filepath, open_mode) as f:
                        while True:
                            if self.active_downloads.get(item_id, {}).get('cancel'):
                                raise Exception("Paused")
                            chunk = resp.read(65536)
                            if not chunk: break
                            f.write(chunk)
                            downloaded += len(chunk)
                            
                            now = time.time()
                            elapsed = now - start_time
                            speed = (downloaded - existing_size) / elapsed if elapsed > 0 else 0
                            progress_callback(item_id, downloaded, total_size, speed)
                            
                finish_callback(item_id, filepath)
            except Exception as e:
                error_callback(item_id, str(e))

        threading.Thread(target=download_thread, daemon=True).start()

    def pause_download(self, item_id):
        if item_id in self.active_downloads:
            self.active_downloads[item_id]['cancel'] = True
