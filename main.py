import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import yt_dlp
import pyperclip

class ProfessionalIDM:
    def __init__(self, root):
        self.root = root
        self.root.title("My_DM - Professional Dashboard")
        self.root.geometry("950x600")
        
        self.bg_dark = "#1e1e1e"
        self.bg_panel = "#252526"
        self.bg_toolbar = "#333333"
        self.fg_text = "#cccccc"
        self.accent = "#007acc"
        
        self.root.configure(bg=self.bg_dark)
        self.download_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        
        self.setup_styles()
        self.setup_ui()
        self.check_clipboard()
        
    def setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background=self.bg_panel, foreground="white", rowheight=28, fieldbackground=self.bg_panel, bordercolor="#333333", borderwidth=0)
        style.map('Treeview', background=[('selected', self.accent)])
        style.configure("Treeview.Heading", background=self.bg_toolbar, foreground="white", font=('Arial', 9, 'bold'))

    def setup_ui(self):
        toolbar = tk.Frame(self.root, bg=self.bg_toolbar, height=60)
        toolbar.pack(side="top", fill="x")
        
        tk.Button(toolbar, text="➕ Add URL", bg="#4CAF50", fg="white", font=("Arial", 9, "bold"), relief="flat", padx=15, pady=8, command=self.add_url).pack(side="left", padx=10, pady=10)
        tk.Button(toolbar, text="▶ Start Queue", bg="#007bff", fg="white", font=("Arial", 9, "bold"), relief="flat", padx=15, pady=8, command=self.start_queue).pack(side="left", padx=5)
        tk.Button(toolbar, text="⏹ Stop / Pause", bg="#dc3545", fg="white", font=("Arial", 9, "bold"), relief="flat", padx=15, pady=8, command=self.stop_download).pack(side="left", padx=5)
        tk.Button(toolbar, text="📁 Change Folder", bg="#6c757d", fg="white", font=("Arial", 9, "bold"), relief="flat", padx=15, pady=8, command=self.browse_folder).pack(side="left", padx=5)
        
        main_frame = tk.Frame(self.root, bg=self.bg_dark)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        sidebar = tk.Frame(main_frame, bg=self.bg_panel, width=160)
        sidebar.pack(side="left", fill="y", padx=(0, 10))
        
        tk.Label(sidebar, text="Categories", bg=self.bg_panel, fg="white", font=("Arial", 10, "bold")).pack(pady=15, anchor="w", padx=10)
        tk.Button(sidebar, text="📂 All Downloads", bg=self.bg_panel, fg=self.fg_text, relief="flat", anchor="w", font=("Arial", 9)).pack(fill="x", padx=5, pady=2, ipady=3)
        tk.Button(sidebar, text="✅ Finished", bg=self.bg_panel, fg=self.fg_text, relief="flat", anchor="w", font=("Arial", 9)).pack(fill="x", padx=5, pady=2, ipady=3)
        tk.Button(sidebar, text="⏳ Queued", bg=self.bg_panel, fg=self.fg_text, relief="flat", anchor="w", font=("Arial", 9)).pack(fill="x", padx=5, pady=2, ipady=3)
        
        columns = ("id", "file_name", "size", "status", "progress", "speed")
        self.tree = ttk.Treeview(main_frame, columns=columns, show="headings")
        
        self.tree.heading("id", text="ID")
        self.tree.column("id", width=40, anchor="center")
        self.tree.heading("file_name", text="File Name / URL")
        self.tree.column("file_name", width=320)
        self.tree.heading("size", text="Size")
        self.tree.column("size", width=80, anchor="center")
        self.tree.heading("status", text="Status")
        self.tree.column("status", width=100, anchor="center")
        self.tree.heading("progress", text="Progress")
        self.tree.column("progress", width=80, anchor="center")
        self.tree.heading("speed", text="Transfer Rate")
        self.tree.column("speed", width=100, anchor="center")
        self.tree.pack(side="left", fill="both", expand=True)
        
        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        
        self.statusbar = tk.Label(self.root, text=f" Save Directory: {self.download_dir}  |  Status: Ready", anchor="w", bg=self.bg_toolbar, fg=self.fg_text, font=("Arial", 9), pady=5)
        self.statusbar.pack(side="bottom", fill="x")
        
        self.queue = []
        self.is_downloading = False
        self.cancel_download = False
        self.last_clipboard = ""
        self.download_id = 1
        
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
            item_id = self.tree.insert("", "end", values=(self.download_id, url, "Unknown", "Queued", "0%", "-"))
            self.queue.append({'item_id': item_id, 'url': url})
            self.download_id += 1

    def browse_folder(self):
        selected_dir = filedialog.askdirectory(initialdir=self.download_dir)
        if selected_dir:
            self.download_dir = selected_dir
            self.statusbar.config(text=f" Save Directory: {self.download_dir}  |  Status: Ready")
            
    def stop_download(self):
        if self.is_downloading:
            self.cancel_download = True
            self.statusbar.config(text=f" Save Directory: {self.download_dir}  |  Status: Stopping (Will pause)...")

    def progress_hook(self, d, item_id):
        if self.cancel_download:
            raise Exception("Stopped by user")
            
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            if total > 0:
                percent = (d.get('downloaded_bytes', 0) / total) * 100
                speed = d.get('speed', 0)
                speed_str = f"{speed / (1024*1024):.2f} MB/s" if speed else "N/A"
                size_str = f"{total / (1024*1024):.2f} MB"
                short_name = os.path.basename(d.get('filename', 'Unknown'))
                self.tree.item(item_id, values=(self.tree.item(item_id)['values'][0], short_name, size_str, "Downloading", f"{percent:.1f}%", speed_str))
        elif d['status'] == 'finished':
            self.tree.item(item_id, values=(self.tree.item(item_id)['values'][0], os.path.basename(d.get('filename', '')), "Unknown", "Processing...", "100%", "Done"))

    def process_queue(self):
        self.is_downloading = True
        self.cancel_download = False
        
        while self.queue and not self.cancel_download:
            task = self.queue[0]
            item_id = task['item_id']
            url = task['url']
            
            self.tree.item(item_id, values=(self.tree.item(item_id)['values'][0], url, "-", "Connecting...", "0%", "-"))
            
            opts = {
                'outtmpl': os.path.join(self.download_dir, '%(title)s.%(ext)s'),
                'progress_hooks': [lambda d: self.progress_hook(d, item_id)],
                'format': 'best'
            }
            
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.download([url])
                self.tree.item(item_id, values=(self.tree.item(item_id)['values'][0], self.tree.item(item_id)['values'][1], self.tree.item(item_id)['values'][2], "Complete", "100%", "Done"))
                self.queue.pop(0)
            except Exception as e:
                if str(e) == "Stopped by user":
                    self.tree.item(item_id, values=(self.tree.item(item_id)['values'][0], url, "-", "Paused", "-", "-"))
                    break
                else:
                    self.tree.item(item_id, values=(self.tree.item(item_id)['values'][0], url, "-", "Error", "-", "-"))
                    self.queue.pop(0)
        
        self.is_downloading = False
        if not self.cancel_download and not self.queue:
            has_error = False
            for child in self.tree.get_children():
                if self.tree.item(child)['values'][3] == "Error":
                    has_error = True
                    break
            
            if has_error:
                self.statusbar.config(text=f" Save Directory: {self.download_dir}  |  Status: Processed with Errors")
                messagebox.showwarning("Finished", "কিউ শেষ হয়েছে, তবে কিছু লিংক ডাউনলোডে এরর হয়েছে!")
            else:
                self.statusbar.config(text=f" Save Directory: {self.download_dir}  |  Status: All Downloads Finished")
                messagebox.showinfo("Success", "সব ডাউনলোড সফলভাবে সম্পন্ন হয়েছে!")

    def start_queue(self):
        if not self.queue:
            return messagebox.showwarning("Warning", "Queue is empty!")
        if not self.is_downloading:
            threading.Thread(target=self.process_queue, daemon=True).start()

if __name__ == "__main__":
    app_root = tk.Tk()
    ProfessionalIDM(app_root)
    app_root.mainloop()
