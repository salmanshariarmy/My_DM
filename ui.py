import tkinter as tk
from tkinter import ttk, messagebox
import time
import os
import subprocess

class DownloadProgressDialog(tk.Toplevel):
    def __init__(self, parent, item_id, filename, total_size, pause_callback, cancel_callback):
        super().__init__(parent)
        self.item_id = item_id
        self.pause_callback = pause_callback
        self.cancel_callback = cancel_callback
        
        self.title(f"Downloading File Info - {filename}")
        self.geometry("550x350")
        self.configure(bg="#333333")
        self.resizable(False, False)
        
        self.lbl_status = tk.Label(self, text="Status: Receiving data...", bg="#333333", fg="white", font=("Arial", 10))
        self.lbl_status.pack(anchor="w", padx=20, pady=(20, 5))
        
        size_str = f"{total_size/(1024*1024):.2f} MB" if total_size > 0 else "Unknown"
        self.lbl_total = tk.Label(self, text=f"File size: {size_str}", bg="#333333", fg="white", font=("Arial", 10))
        self.lbl_total.pack(anchor="w", padx=20, pady=2)
        
        self.lbl_downloaded = tk.Label(self, text="Downloaded: 0.00 MB", bg="#333333", fg="white", font=("Arial", 10))
        self.lbl_downloaded.pack(anchor="w", padx=20, pady=2)
        
        self.lbl_speed = tk.Label(self, text="Transfer rate: 0 KB/s", bg="#333333", fg="white", font=("Arial", 10))
        self.lbl_speed.pack(anchor="w", padx=20, pady=2)
        
        self.lbl_time = tk.Label(self, text="Time left: Calculating...", bg="#333333", fg="white", font=("Arial", 10))
        self.lbl_time.pack(anchor="w", padx=20, pady=2)
        
        self.progress = ttk.Progressbar(self, orient="horizontal", length=510, mode="determinate")
        self.progress.pack(pady=20)
        
        tk.Button(self, text="<< Hide details", bg="#555", fg="white").place(x=20, y=300)
        
        tk.Button(self, text="Pause", bg="#555", fg="white", command=self.on_pause).place(x=380, y=300)
        tk.Button(self, text="Cancel", bg="#555", fg="white", command=self.on_cancel).place(x=450, y=300)

    def on_pause(self):
        self.pause_callback(self.item_id)
        self.destroy()
        
    def on_cancel(self):
        self.cancel_callback(self.item_id)
        self.destroy()

    def update_progress(self, downloaded, total, speed):
        if total > 0:
            percent = (downloaded / total) * 100
            self.progress['value'] = percent
            eta = (total - downloaded) / speed if speed > 0 else 0
            self.lbl_time.config(text=f"Time left: {time.strftime('%H:%M:%S', time.gmtime(eta))}")
            self.lbl_downloaded.config(text=f"Downloaded: {downloaded/(1024*1024):.2f} MB ( {percent:.1f}% )")
        else:
            self.lbl_downloaded.config(text=f"Downloaded: {downloaded/(1024*1024):.2f} MB")
            
        self.lbl_speed.config(text=f"Transfer rate: {speed/(1024*1024):.2f} MB/s")


class IDM_UI:
    def __init__(self, root, engine):
        self.root = root
        self.engine = engine
        self.root.title("Internet Download Manager Clone")
        self.root.geometry("1100x650")
        self.root.configure(bg="#1e1e1e")
        
        self.tasks = {}
        self.dialogs = {}
        self.item_counter = 1
        self.current_filter = "All Downloads"
        
        self.setup_styles()
        self.setup_ui()

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background="#252526", foreground="white", rowheight=25, fieldbackground="#252526", borderwidth=0)
        style.map('Treeview', background=[('selected', '#007acc')])
        style.configure("Treeview.Heading", background="#333", foreground="white", font=('Arial', 9, 'bold'))

    def setup_ui(self):
        toolbar = tk.Frame(self.root, bg="#333", height=70)
        toolbar.pack(side="top", fill="x")
        
        btns = [
            ("➕", "Add URL", self.add_new_url),
            ("⏯", "Resume", self.resume_task),
            ("⏹", "Stop", self.stop_task),
            ("🛑", "Stop All", self.stop_all),
            ("❌", "Delete", self.delete_task),
            ("🧹", "Delete C...", self.delete_completed),
            ("📂", "Open Folder", self.open_folder),
            ("⚙️", "Options", None),
            ("ℹ️", "Properties", self.show_properties)
        ]
        
        for icon, text, cmd in btns:
            tk.Button(toolbar, text=f"{icon}\n{text}", bg="#333", fg="white", font=("Arial", 8), relief="flat", command=cmd).pack(side="left", padx=5, pady=5)

        main_frame = tk.Frame(self.root, bg="#1e1e1e")
        main_frame.pack(fill="both", expand=True, padx=5, pady=5)
        
        sidebar = tk.Frame(main_frame, bg="#252526", width=180)
        sidebar.pack(side="left", fill="y", padx=(0, 5))
        
        tk.Label(sidebar, text="Categories", bg="#252526", fg="white", font=("Arial", 10, "bold")).pack(pady=10, anchor="w", padx=10)
        cats = ["All Downloads", "Compressed", "Documents", "Music", "Programs", "Video", "Finished", "Queues"]
        
        for cat in cats:
            lbl = tk.Label(sidebar, text=f"📁 {cat}", bg="#252526", fg="#ccc", font=("Arial", 9), cursor="hand2")
            lbl.pack(anchor="w", padx=20, pady=5)
            lbl.bind("<Button-1>", lambda e, c=cat: self.apply_filter(c))

        cols = ("file", "size", "status", "time", "speed", "url")
        self.tree = ttk.Treeview(main_frame, columns=cols, show="headings")
        self.tree.heading("file", text="File Name"); self.tree.column("file", width=250)
        self.tree.heading("size", text="Size"); self.tree.column("size", width=80, anchor="center")
        self.tree.heading("status", text="Status"); self.tree.column("status", width=100, anchor="center")
        self.tree.heading("time", text="Time left"); self.tree.column("time", width=80, anchor="center")
        self.tree.heading("speed", text="Transfer rate"); self.tree.column("speed", width=100, anchor="center")
        self.tree.heading("url", text="URL"); self.tree.column("url", width=250)
        self.tree.pack(side="left", fill="both", expand=True)
        
        # Double click to open file
        self.tree.bind("<Double-1>", lambda e: self.open_folder())

    # --- Filtering and Folder Logic ---
    def apply_filter(self, category):
        self.current_filter = category
        for item in self.tree.get_children():
            self.tree.detach(item)
            
        for item_id, task in self.tasks.items():
            status = task.get('status_text', '')
            cat_folder = self.engine.get_category_folder(task['filename'])
            
            show = False
            if category == "All Downloads": show = True
            elif category == "Finished" and status == "Complete": show = True
            elif category == "Queues" and status != "Complete": show = True
            elif category == cat_folder: show = True
            
            if show:
                self.tree.reattach(item_id, "", "end")

    def open_folder(self):
        selected = self.tree.selection()
        if not selected:
            # Open base directory if nothing is selected
            os.startfile(self.engine.base_dir) if os.name == 'nt' else subprocess.call(['xdg-open', self.engine.base_dir])
            return
            
        item_id = selected[0]
        task = self.tasks.get(item_id)
        if task:
            cat_folder = self.engine.get_category_folder(task['filename'])
            folder_path = os.path.join(self.engine.base_dir, cat_folder)
            if os.path.exists(folder_path):
                if os.name == 'nt':
                    os.startfile(folder_path)
                else:
                    subprocess.call(['xdg-open', folder_path])

    def add_new_url(self):
        import tkinter.simpledialog as sd
        url = sd.askstring("Add URL", "Enter URL to download:", parent=self.root)
        if url:
            fname, size = self.engine.fetch_info(url)
            self.show_pre_download_dialog(url, fname, size)

    def show_pre_download_dialog(self, url, fname, size):
        dlg = tk.Toplevel(self.root)
        dlg.title("Download File Info")
        dlg.geometry("550x250")
        dlg.configure(bg="#252526")
        
        url_frame = tk.Frame(dlg, bg="#252526")
        url_frame.pack(fill="x", padx=20, pady=(30, 10))
        tk.Label(url_frame, text="URL:", bg="#252526", fg="white", width=8, anchor="w").pack(side="left")
        url_entry = tk.Entry(url_frame, bg="#333333", fg="#aaaaaa", relief="flat")
        url_entry.insert(0, url)
        url_entry.config(state="readonly")
        url_entry.pack(side="left", fill="x", expand=True)
        
        save_frame = tk.Frame(dlg, bg="#252526")
        save_frame.pack(fill="x", padx=20, pady=10)
        tk.Label(save_frame, text="Save As:", bg="#252526", fg="white", width=8, anchor="w").pack(side="left")
        path = tk.Entry(save_frame, bg="white", fg="black")
        default_path = os.path.join(self.engine.base_dir, self.engine.get_category_folder(fname), fname)
        path.insert(0, default_path)
        path.pack(side="left", fill="x", expand=True)
        
        def start():
            item_id = f"task_{self.item_counter}"
            self.item_counter += 1
            size_str = f"{size/(1024*1024):.2f} MB" if size > 0 else "Unknown"
            
            self.tree.insert("", "end", iid=item_id, values=(fname, size_str, "Connecting...", "-", "-", url))
            self.tasks[item_id] = {'url': url, 'filename': fname, 'size': size, 'status_text': 'Connecting...'}
            self.apply_filter(self.current_filter) # apply filter for new item
            
            self.dialogs[item_id] = DownloadProgressDialog(
                self.root, item_id, fname, size, 
                self.pause_specific_task, self.cancel_specific_task
            )
            self.engine.start_download(item_id, url, fname, self.progress_cb, self.finish_cb, self.error_cb)
            dlg.destroy()
            
        tk.Button(dlg, text="Start Download", bg="#007acc", fg="white", font=("Arial", 10, "bold"), padx=15, pady=5, command=start).pack(pady=30)

    def pause_specific_task(self, item_id):
        self.engine.pause_download(item_id)
        
    def cancel_specific_task(self, item_id):
        self.engine.pause_download(item_id)
        if self.tree.exists(item_id): self.tree.delete(item_id)
        if item_id in self.tasks: del self.tasks[item_id]

    def update_task_status(self, item_id, status_text):
        if item_id in self.tasks:
            self.tasks[item_id]['status_text'] = status_text
        if self.current_filter in ["Finished", "Queues"]:
            self.apply_filter(self.current_filter)

    def progress_cb(self, item_id, downloaded, total, speed):
        try:
            percent = f"{(downloaded/total)*100:.1f}%" if total > 0 else "DL..."
            speed_str = f"{speed/(1024*1024):.2f} MB/s"
            
            self.update_task_status(item_id, percent)
            
            if self.tree.exists(item_id):
                curr = list(self.tree.item(item_id, "values"))
                curr[2] = percent
                curr[4] = speed_str
                self.tree.item(item_id, values=curr)
            
            if item_id in self.dialogs and self.dialogs[item_id].winfo_exists():
                self.dialogs[item_id].update_progress(downloaded, total, speed)
        except: pass

    def finish_cb(self, item_id, filepath):
        try:
            self.update_task_status(item_id, "Complete")
            if self.tree.exists(item_id):
                curr = list(self.tree.item(item_id, "values"))
                curr[2] = "Complete"
                curr[3] = "-"
                curr[4] = "Done"
                self.tree.item(item_id, values=curr)
            if item_id in self.dialogs and self.dialogs[item_id].winfo_exists():
                self.dialogs[item_id].destroy()
        except: pass

    def error_cb(self, item_id, err_msg):
        try:
            status = "Paused" if err_msg == "Paused" else "Error"
            self.update_task_status(item_id, status)
            if self.tree.exists(item_id):
                curr = list(self.tree.item(item_id, "values"))
                curr[2] = status
                curr[4] = "-"
                self.tree.item(item_id, values=curr)
        except: pass

    def stop_task(self):
        for item_id in self.tree.selection():
            self.engine.pause_download(item_id)

    def stop_all(self):
        for item_id in self.tasks:
            self.engine.pause_download(item_id)

    def resume_task(self):
        for item_id in self.tree.selection():
            task = self.tasks.get(item_id)
            if task:
                status = task.get('status_text', '')
                if status in ["Paused", "Error"]:
                    self.dialogs[item_id] = DownloadProgressDialog(
                        self.root, item_id, task['filename'], task['size'], 
                        self.pause_specific_task, self.cancel_specific_task
                    )
                    self.engine.start_download(item_id, task['url'], task['filename'], self.progress_cb, self.finish_cb, self.error_cb)

    def delete_task(self):
        for item_id in self.tree.selection():
            self.cancel_specific_task(item_id)

    def delete_completed(self):
        for item_id in list(self.tasks.keys()):
            if self.tasks[item_id].get('status_text') == "Complete":
                if self.tree.exists(item_id): self.tree.delete(item_id)
                del self.tasks[item_id]

    def show_properties(self):
        selected = self.tree.selection()
        if not selected: return
        item_id = selected[0]
        vals = self.tree.item(item_id)['values']
        
        prop = tk.Toplevel(self.root)
        prop.title("File Properties")
        prop.geometry("450x300")
        prop.configure(bg="#f0f0f0")
        
        tk.Label(prop, text=f"File Name: {vals[0]}", font=("Arial", 10, "bold")).pack(pady=10, anchor="w", padx=20)
        tk.Label(prop, text=f"Size: {vals[1]}").pack(anchor="w", padx=20, pady=2)
        tk.Label(prop, text=f"Status: {vals[2]}").pack(anchor="w", padx=20, pady=2)
        tk.Label(prop, text=f"Address: {vals[5]}").pack(anchor="w", padx=20, pady=2)
        tk.Button(prop, text="OK", command=prop.destroy, width=10).pack(pady=20)
