import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os

class IDM_UI:
    def __init__(self, root, engine):
        self.root = root
        self.engine = engine
        self.root.title("My_DM - Professional Dashboard")
        self.root.geometry("1000x650")
        self.root.configure(bg="#1e1e1e")
        
        self.tasks = {}
        self.setup_ui()

    def setup_ui(self):
        # Toolbar
        toolbar = tk.Frame(self.root, bg="#333", height=70)
        toolbar.pack(side="top", fill="x")
        
        tk.Button(toolbar, text="➕\nAdd URL", bg="#333", fg="white", command=self.show_add_url_dialog).pack(side="left", padx=5, pady=5)
        tk.Button(toolbar, text="ℹ️\nProperties", bg="#333", fg="white", command=self.show_properties).pack(side="left", padx=5, pady=5)
        
        # Table
        columns = ("id", "file", "size", "status")
        self.tree = ttk.Treeview(self.root, columns=columns, show="headings")
        for col in columns: self.tree.heading(col, text=col.capitalize())
        self.tree.pack(fill="both", expand=True, padx=10, pady=10)

    # 1. Download File Info Dialog (Matches Image 2)
    def show_add_url_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Download File Info")
        dialog.geometry("500x250")
        dialog.configure(bg="#252526")
        
        tk.Label(dialog, text="URL:", bg="#252526", fg="white").place(x=20, y=20)
        url_entry = tk.Entry(dialog, width=50)
        url_entry.place(x=80, y=20)
        
        tk.Label(dialog, text="Save As:", bg="#252526", fg="white").place(x=20, y=60)
        path_entry = tk.Entry(dialog, width=50)
        path_entry.insert(0, self.engine.download_dir)
        path_entry.place(x=80, y=60)
        
        def start_dl():
            url = url_entry.get()
            if url:
                filename, size = self.engine.get_file_info(url)
                item = self.tree.insert("", "end", values=("1", filename, f"{size/(1024*1024):.2f} MB", "Downloading..."))
                dialog.destroy()
                self.show_download_status(filename, size) # Open Live Status
        
        tk.Button(dialog, text="Start Download", command=start_dl).place(x=200, y=200)

    # 2. Live Download Status Dialog (Matches Image 3)
    def show_download_status(self, filename, size):
        status_win = tk.Toplevel(self.root)
        status_win.title(f"Downloading - {filename}")
        status_win.geometry("500x400")
        status_win.configure(bg="#2b2b2b")
        
        tk.Label(status_win, text=f"File size: {size/(1024*1024):.2f} MB", bg="#2b2b2b", fg="white").pack(anchor="w", padx=20, pady=10)
        tk.Label(status_win, text="Status: Receiving data...", bg="#2b2b2b", fg="white").pack(anchor="w", padx=20)
        
        progress = ttk.Progressbar(status_win, orient="horizontal", length=450, mode="determinate")
        progress.pack(pady=20)
        
        tk.Button(status_win, text="Pause").pack()

    # 3. File Properties Dialog (Matches Image 1)
    def show_properties(self):
        selected = self.tree.selection()
        if not selected: return
        
        prop_win = tk.Toplevel(self.root)
        prop_win.title("File Properties")
        prop_win.geometry("450x350")
        
        file_name = self.tree.item(selected[0])['values'][1]
        tk.Label(prop_win, text=file_name, font=("Arial", 10, "bold")).pack(pady=10)
        tk.Label(prop_win, text=f"Save To: {self.engine.download_dir}").pack(anchor="w", padx=20, pady=5)
        tk.Label(prop_win, text="Status: Complete").pack(anchor="w", padx=20, pady=5)
        tk.Button(prop_win, text="Open File", width=15).pack(pady=20)
