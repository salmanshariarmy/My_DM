import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import yt_dlp

class IDMDownloader:
    def __init__(self, root):
        self.root = root
        self.root.title("My Personal Downloader")
        self.root.geometry("600x320")
        self.root.resizable(False, False)
        self.download_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        self.setup_ui()

    def setup_ui(self):
        tk.Label(self.root, text="URL / Link:", font=("Arial", 11, "bold")).pack(anchor="w", padx=20, pady=(20, 5))
        self.entry_url = tk.Entry(self.root, width=65, font=("Arial", 10))
        self.entry_url.pack(padx=20, fill="x")

        dir_frame = tk.Frame(self.root)
        dir_frame.pack(fill="x", padx=20, pady=10)
        self.lbl_path = tk.Label(dir_frame, text=f"Save To: {self.download_dir}", font=("Arial", 9))
        self.lbl_path.pack(side="left")
        tk.Button(dir_frame, text="Browse...", command=self.browse_folder).pack(side="right")

        self.progress_bar = ttk.Progressbar(self.root, orient="horizontal", mode="determinate")
        self.progress_bar.pack(fill="x", padx=20, pady=10)
        self.lbl_status = tk.Label(self.root, text="স্ট্যাটাস: অপেক্ষা করা হচ্ছে...", font=("Arial", 9))
        self.lbl_status.pack(padx=20, anchor="w")

        self.btn_download = tk.Button(self.root, text="Download Start", bg="#28a745", fg="white", font=("Arial", 11, "bold"), command=self.start_download_thread)
        self.btn_download.pack(pady=15, ipadx=10, ipady=3)

    def browse_folder(self):
        selected_dir = filedialog.askdirectory(initialdir=self.download_dir)
        if selected_dir:
            self.download_dir = selected_dir
            self.lbl_path.config(text=f"Save To: {self.download_dir}")

    def progress_hook(self, d):
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            if total > 0:
                percent = (d.get('downloaded_bytes', 0) / total) * 100
                self.progress_bar['value'] = percent
                speed = d.get('speed', 0)
                speed_str = f"{speed / (1024*1024):.2f} MB/s" if speed else "N/A"
                self.lbl_status.config(text=f"ডাউনলোড: {percent:.1f}% | গতি: {speed_str}")
        elif d['status'] == 'finished':
            self.lbl_status.config(text="প্রসেসিং চলছে...")

    def run_download(self, url):
        opts = {'outtmpl': os.path.join(self.download_dir, '%(title)s.%(ext)s'), 'progress_hooks': [self.progress_hook], 'format': 'best'}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl: ydl.download([url])
            self.lbl_status.config(text="সফলভাবে সম্পন্ন হয়েছে!")
            messagebox.showinfo("Success", "ডাউনলোড কমপ্লিট!")
        except Exception as e:
            self.lbl_status.config(text="ত্রুটি!")
            messagebox.showerror("Error", str(e))
        finally:
            self.btn_download.config(state="normal")
            self.progress_bar['value'] = 0

    def start_download_thread(self):
        url = self.entry_url.get().strip()
        if not url: return messagebox.showwarning("Warning", "লিংক দিন!")
        self.btn_download.config(state="disabled")
        threading.Thread(target=self.run_download, args=(url,), daemon=True).start()

if __name__ == "__main__":
    app_root = tk.Tk()
    IDMDownloader(app_root)
    app_root.mainloop()
