import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import yt_dlp
import pyperclip
import urllib.request
from urllib.error import HTTPError
from urllib.parse import urlparse, unquote
import time
import re

class ProfessionalIDM:
    def __init__(self, root):
        self.root = root
        self.root.title("My_DM - Professional Dashboard")
        self.root.geometry("1000x650")
        
        # Colors (IDM Dark Theme style)
        self.bg_dark = "#1e1e1e"
        self.bg_panel = "#252526"
        self.bg_toolbar = "#333333"
        self.fg_text = "#cccccc"
        self.accent = "#007acc"
        
        self.root.configure(bg=self.bg_dark)
        self.download_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        
        self.tasks = {} # Store task details by item_id
        self.queue = []
        self.is_downloading = False
        self.cancel_download = False
        self.last_clipboard = ""
        self.download_id = 1
        
        self.setup_styles()
        self.setup_ui()
        self.check_clipboard()
        
    def setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background=self.bg_panel, foreground="white", rowheight=25, fieldbackground=self.bg_panel, bordercolor="#333333", borderwidth=0)
        style.map('Treeview', background=[('selected', self.accent)])
        style.configure("Treeview.Heading", background=self.bg_toolbar, foreground="white", font=('Arial', 9, 'bold'))

    def setup_ui(self):
        # Top Toolbar (Mimicking IDM)
        toolbar = tk.Frame(self.root, bg=self.bg_toolbar, height=70)
        toolbar.pack(side="top", fill="x")
        
        # Helper function for toolbar buttons
        def create_btn(parent, icon, text, cmd):
            btn = tk.Button(parent, text=f"{icon}\n{text}", bg=self.bg_toolbar, fg="white", font=("Arial", 8), relief="flat", activebackground="#444", activeforeground="white", cursor="hand2", command=cmd)
            btn.pack(side="left", padx=2, pady=5, ipadx=5, ipady=2)
            return btn

        create_btn(toolbar, "➕", "Add URL", self.add_url)
        
        tk.Frame(toolbar, width=2, bg="#555").pack(side="left", fill="y", pady=10, padx=5) # Separator
        
        create_btn(toolbar, "⏯", "Resume", self.resume_selected)
        create_btn(toolbar, "⏹", "Stop", self.stop_selected)
        create_btn(toolbar, "🛑", "Stop All", self.stop_all)
        
        tk.Frame(toolbar, width=2, bg="#555").pack(side="left", fill="y", pady=10, padx=5) # Separator
        
        create_btn(toolbar, "❌", "Delete", self.delete_selected)
        create_btn(toolbar, "🧹", "Delete C...", self.delete_completed)
        
        tk.Frame(toolbar, width=2, bg="#555").pack(side="left", fill="y", pady=10, padx=5) # Separator
        
        create_btn(toolbar, "▶", "Start Q...", self.start_queue)
        create_btn(toolbar, "⏸", "Stop Q...", self.stop_all)
        create_btn(toolbar, "📁", "Folder", self.browse_folder)
        
        # Main Layout
        main_frame = tk.Frame(self.root, bg=self.bg_dark)
        main_frame.pack(fill="both", expand=True, padx=5, pady=5)
        
        # Downloads Table
        columns = ("id", "file_name", "size", "status", "time_left", "speed", "url")
        self.tree = ttk.Treeview(main_frame, columns=columns, show="headings")
        
        self.tree.heading("id", text="ID")
        self.tree.column("id", width=40, anchor="center")
        self.tree.heading("file_name", text="File Name")
        self.tree.column("file_name", width=300)
        self.tree.heading("size", text="Size")
        self.tree.column("size", width=80, anchor="center")
        self.tree.heading("status", text="Status")
        self.tree.column("status", width=120, anchor="center")
        self.tree.heading("time_left", text="Time left")
        self.tree.column("time_left", width=80, anchor="center")
        self.tree.heading("speed", text="Transfer rate")
        self.tree.column("speed", width=100, anchor="center")
        self.tree.heading("url", text="Description / URL")
        self.tree.column("url", width=250)
        self.tree.pack(side="left", fill="both", expand=True)
        
        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        
        # Status Bar
        self.statusbar = tk.Label(self.root, text=f" Save Directory: {self.download_dir}  |  Status: Ready", anchor="w", bg=self.bg_toolbar, fg=self.fg_text, font=("Arial", 9), pady=5)
        self.statusbar.pack(side="bottom", fill="x")
        
    def check_clipboard(self):
        try:
            clipboard_content = pyperclip.paste()
            if clipboard_content != self.last_clipboard and clipboard_content.startswith("http"):
                self.last_clipboard = clipboard_content
                self.prompt_add_url(clipboard_content)
        except:
            pass
        self.root.after(1500, self.check_clipboard)

    def add_url(self):
        self.prompt_add_url("")
        
    def prompt_add_url(self, default_url):
        url = simpledialog.askstring("Add New Download", "Enter Download URL:", initialvalue=default_url, parent=self.root)
        if url:
            item_id = self.tree.insert("", "end", values=(self.download_id, "Fetching...", "-", "Queued", "-", "-", url))
            self.tasks[item_id] = {'url': url, 'status': 'queued', 'filename': ''}
            self.queue.append(item_id)
            self.download_id += 1

    def browse_folder(self):
        selected_dir = filedialog.askdirectory(initialdir=self.download_dir)
        if selected_dir:
            self.download_dir = selected_dir
            self.statusbar.config(text=f" Save Directory: {self.download_dir}  |  Status: Ready")

    # --- New Toolbar Functions ---
    def delete_selected(self):
        selected = self.tree.selection()
        for item in selected:
            if item in self.queue:
                self.queue.remove(item)
            if item in self.tasks:
                # Stop if currently downloading
                if self.tasks[item]['status'] == 'downloading':
                    self.cancel_download = True 
                del self.tasks[item]
            self.tree.delete(item)

    def delete_completed(self):
        items_to_delete = []
        for child in self.tree.get_children():
            if self.tree.item(child)['values'][3] == "Complete":
                items_to_delete.append(child)
        for item in items_to_delete:
            if item in self.tasks: del self.tasks[item]
            self.tree.delete(item)

    def stop_selected(self):
        selected = self.tree.selection()
        for item in selected:
            if item in self.tasks and self.tasks[item]['status'] == 'downloading':
                self.cancel_download = True
            elif item in self.queue:
                self.queue.remove(item)
                self.update_row(item, status="Paused")
                self.tasks[item]['status'] = 'paused'

    def stop_all(self):
        self.cancel_download = True
        self.queue.clear()
        for child in self.tree.get_children():
            if self.tree.item(child)['values'][3] in ["Queued", "Downloading..."]:
                self.update_row(child, status="Paused")
                self.tasks[child]['status'] = 'paused'
        self.statusbar.config(text=f" Save Directory: {self.download_dir}  |  Status: All stopped")

    def resume_selected(self):
        selected = self.tree.selection()
        for item in selected:
            status = self.tree.item(item)['values'][3]
            if status in ["Paused", "Error", "Stopped"]:
                self.update_row(item, status="Queued")
                self.tasks[item]['status'] = 'queued'
                if item not in self.queue:
                    self.queue.append(item)
        if not self.is_downloading:
            self.start_queue()

    def update_row(self, item_id, name=None, size=None, status=None, time_left=None, speed=None):
        try:
            current = list(self.tree.item(item_id)['values'])
            if name is not None: current[1] = name
            if size is not None: current[2] = size
            if status is not None: current[3] = status
            if time_left is not None: current[4] = time_left
            if speed is not None: current[5] = speed
            self.tree.item(item_id, values=current)
        except: pass

    # --- Core Download Logic ---
    def progress_hook(self, d, item_id):
        if self.cancel_download:
            raise Exception("Stopped by user")
            
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            if total > 0:
                percent = (d.get('downloaded_bytes', 0) / total) * 100
                speed = d.get('speed', 0)
                eta = d.get('eta', 0)
                
                speed_str = f"{speed / (1024*1024):.2f} MB/s" if speed else "N/A"
                size_str = f"{total / (1024*1024):.2f} MB"
                eta_str = time.strftime('%H:%M:%S', time.gmtime(eta)) if eta else "-"
                short_name = os.path.basename(d.get('filename', 'Unknown'))
                
                self.update_row(item_id, short_name, size_str, f"{percent:.1f}%", eta_str, speed_str)
                
        elif d['status'] == 'finished':
            self.update_row(item_id, os.path.basename(d.get('filename', '')), status="Processing...", speed="Done", time_left="-")

    def download_direct_file(self, url, item_id):
        # Basic request to get filename and size
        req = urllib.request.Request(url, method='HEAD', headers={'User-Agent': 'Mozilla/5.0'})
        try:
            with urllib.request.urlopen(req) as response:
                file_size = int(response.getheader('Content-Length', 0))
                cd = response.getheader('Content-Disposition')
                filename = ""
                if cd and 'filename=' in cd:
                    raw_name = cd.split('filename=')[1].split(';')[0].strip(' "\'')
                    filename = unquote(raw_name)
                if not filename:
                    filename = os.path.basename(urlparse(url).path)
                if not filename or len(filename) > 100:
                    filename = f"download_{item_id}_{int(time.time())}.dat"
                
                filename = re.sub(r'[\\/*?:"<>|]', "", filename)
        except:
            filename = f"download_{item_id}_{int(time.time())}.dat"
            file_size = 0

        filepath = os.path.join(self.download_dir, filename)
        
        # Resume Logic (Check if file already exists)
        existing_size = 0
        open_mode = 'wb'
        headers = {'User-Agent': 'Mozilla/5.0'}
        
        if os.path.exists(filepath):
            existing_size = os.path.getsize(filepath)
            if existing_size > 0 and file_size > 0 and existing_size < file_size:
                headers['Range'] = f'bytes={existing_size}-'
                open_mode = 'ab'
            elif existing_size >= file_size and file_size > 0:
                self.update_row(item_id, filename, f"{file_size / (1024*1024):.2f} MB", "Complete", "-", "Done")
                return

        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as response:
            downloaded = existing_size
            start_time = time.time()
            last_update = 0
            
            with open(filepath, open_mode) as f:
                while True:
                    if self.cancel_download:
                        raise Exception("Stopped by user")
                    chunk = response.read(65536)
                    if not chunk: break
                    f.write(chunk)
                    downloaded += len(chunk)
                    
                    now = time.time()
                    if now - last_update > 0.5:
                        last_update = now
                        elapsed = now - start_time
                        speed = (downloaded - existing_size) / elapsed if elapsed > 0 else 0
                        speed_str = f"{speed / (1024*1024):.2f} MB/s"
                        
                        if file_size > 0:
                            percent = (downloaded / file_size) * 100
                            eta = (file_size - downloaded) / speed if speed > 0 else 0
                            eta_str = time.strftime('%H:%M:%S', time.gmtime(eta))
                            size_str = f"{file_size / (1024*1024):.2f} MB"
                            self.update_row(item_id, filename, size_str, f"{percent:.1f}%", eta_str, speed_str)
                        else:
                            size_str = f"{downloaded / (1024*1024):.2f} MB"
                            self.update_row(item_id, filename, size_str, "Direct DL...", "-", speed_str)

            size_str_final = f"{file_size / (1024*1024):.2f} MB" if file_size > 0 else f"{downloaded / (1024*1024):.2f} MB"
            self.update_row(item_id, filename, size_str_final, "Complete", "-", "Done")

    def process_queue(self):
        self.is_downloading = True
        self.cancel_download = False
        
        while self.queue and not self.cancel_download:
            item_id = self.queue[0]
            if item_id not in self.tasks:
                self.queue.pop(0)
                continue
                
            url = self.tasks[item_id]['url']
            self.tasks[item_id]['status'] = 'downloading'
            self.update_row(item_id, status="Connecting...")
            
            opts = {
                'outtmpl': os.path.join(self.download_dir, '%(title)s.%(ext)s'),
                'progress_hooks': [lambda d: self.progress_hook(d, item_id)],
                'format': 'best',
                'nocheckcertificate': True,
                'continuedl': True # Enable native yt-dlp resume
            }
            
            try:
                with yt_dlp.YoutubeDL(opts) as ydl: ydl.download([url])
                self.update_row(item_id, status="Complete", time_left="-", speed="Done")
                self.tasks[item_id]['status'] = 'complete'
                if self.queue: self.queue.pop(0)
                
            except Exception as e:
                if str(e) == "Stopped by user":
                    self.update_row(item_id, status="Paused", time_left="-", speed="-")
                    self.tasks[item_id]['status'] = 'paused'
                    break
                else:
                    try:
                        self.update_row(item_id, status="Direct DL...")
                        self.download_direct_file(url, item_id)
                        self.tasks[item_id]['status'] = 'complete'
                        if self.queue: self.queue.pop(0)
                    except Exception as direct_e:
                        if str(direct_e) == "Stopped by user":
                            self.update_row(item_id, status="Paused", time_left="-", speed="-")
                            self.tasks[item_id]['status'] = 'paused'
                            break
                        self.update_row(item_id, status="Error", time_left="-", speed="-")
                        self.tasks[item_id]['status'] = 'error'
                        if self.queue: self.queue.pop(0)
        
        self.is_downloading = False
        if not self.cancel_download and not self.queue:
            self.statusbar.config(text=f" Save Directory: {self.download_dir}  |  Status: Queue Finished")

    def start_queue(self):
        if not self.queue:
            return messagebox.showwarning("Warning", "Queue is empty or all items are paused!")
        if not self.is_downloading:
            threading.Thread(target=self.process_queue, daemon=True).start()

if __name__ == "__main__":
    app_root = tk.Tk()
    ProfessionalIDM(app_root)
    app_root.mainloop()
