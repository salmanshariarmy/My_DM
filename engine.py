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
        self.active_downloads = {} 

    def get_category_folder(self, filename):
        ext = filename.split('.')[-1].lower() if '.' in filename else ''
        if ext in ['mp4', 'mkv', 'avi', 'mov', 'webm']: return "Video"
        elif ext in ['mp3', 'wav', 'aac', 'flac', 'm4a']: return "Music"
        elif ext in ['zip', 'rar', '7z', 'tar', 'gz']: return "Compressed"
        elif ext in ['pdf', 'doc', 'docx', 'txt', 'xlsx']: return "Documents"
        elif ext in ['exe', 'msi', 'apk']: return "Programs"
        return "General"

    def fetch_info(self, url):
        # ১. ইউটিউব, ফেসবুক বা ভিডিও সাইট হলে yt-dlp দিয়ে আসল ফাইলের নাম ও সাইজ বের করবে
        if any(domain in url for domain in ['youtube.com', 'youtu.be', 'facebook.com', 'vimeo.com', 'tiktok.com']):
            try:
                ydl_opts = {'quiet': True, 'noplaylist': True}
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    title = info.get('title', f"video_{int(time.time())}")
                    ext = info.get('ext', 'mp4')
                    filename = f"{title}.{ext}"
                    filename = re.sub(r'[\\/*?:"<>|]', "", filename)
                    size = info.get('filesize') or info.get('filesize_approx') or 0
                    return filename, size
            except:
                pass
                
        # ২. সাধারণ ডিরেক্ট লিংক হলে HTTP Request দিয়ে ইনফো নেবে
        try:
            req = urllib.request.Request(url, method='HEAD', headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=5) as resp:
                size = int(resp.getheader('Content-Length', 0))
                cd = resp.getheader('Content-Disposition')
                fname = ""
                if cd and 'filename=' in cd:
                    fname = unquote(cd.split('filename=')[1].split(';')[0].strip(' "\''))
                if not fname: fname = os.path.basename(urlparse(url).path)
                if not fname or fname == "watch": fname = f"file_{int(time.time())}.mp4"
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
            # ১. YouTube/Video সাইটের লিংক হলে yt-dlp দিয়ে ভিডিও ডাউনলোড করবে
            if any(domain in url for domain in ['youtube.com', 'youtu.be', 'facebook.com', 'vimeo.com', 'tiktok.com']):
                try:
                    def ytdl_hook(d):
                        if self.active_downloads.get(item_id, {}).get('cancel'):
                            raise Exception("Paused")
                        if d['status'] == 'downloading':
                            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                            downloaded = d.get('downloaded_bytes', 0)
                            speed = d.get('speed', 0)
                            progress_callback(item_id, downloaded, total, speed)

                    opts = {
                        'outtmpl': filepath,
                        'progress_hooks': [ytdl_hook],
                        'format': 'best',
                        'nocheckcertificate': True,
                        'continuedl': True,
                        'quiet': True
                    }
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        ydl.download([url])
                    finish_callback(item_id, filepath)
                    return
                except Exception as e:
                    if str(e) == "Paused":
                        error_callback(item_id, "Paused")
                        return
                    pass # Error হলে নিচের HTTP লজিকে ট্রাই করবে

            # ২. সাধারণ ফাইলের জন্য ডিরেক্ট HTTP Download (Resume সাপোর্টসহ)
            try:
                existing_size = os.path.getsize(filepath) if os.path.exists(filepath) else 0
                headers = {'User-Agent': 'Mozilla/5.0'}
                open_mode = 'wb'
                
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
