import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import yt_dlp
import pyperclip

class AdvancedIDM:
    def __init__(self, root):
        self.root = root
        self.root.title("My_DM - Advanced Manager")
        self.root.geometry("650x550")
        
        # Dark Mode Colors
        self.bg_color = "#1e1e1e"
        self.fg_color = "#e0e0e0"
        self.root.configure(bg=self.bg_color)

        self.download_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        self.queue = []
        self.is_downloading = False
        self.cancel_download = False
        self.last_clipboard = ""

        self.setup_ui()
        self.check_clipboard() # Start clipboard monitor

    def setup_ui(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("TProgressbar", thickness=15, troughcolor='#333333', background='#28a745')

        # Title & URL Entry
        tk.Label(self.root, text="URL / Link:", font=("Arial", 11, "bold"), bg=self.bg_color, fg=self.fg_color).pack(anchor="w", padx=20, pady=(15, 5))
        
        url_frame = tk.Frame(self.root, bg=self.bg_color)
        url_frame.pack(fill="x", padx=20)
        self.entry_url = tk.Entry(url_frame, width=55, font=("Arial", 10), bg="#333", fg="white", insertbackground="white")
        self.entry_url.pack(side="left", fill="x", expand=True, ipady=4)
        
        tk.Button(url_frame, text="Add to Queue", bg="#007bff", fg="white", command=self.add_to_queue).pack(side="right", padx=(10, 0))

        # Queue Listbox
        tk.Label(self.root, text="Download Queue:", font=("Arial", 10, "bold"), bg=self.bg_color, fg=self.fg_color).pack(anchor="w", padx=20, pady=(15, 5))
        self.listbox_queue = tk.Listbox(self.root, height=6, bg="#2b2b2b", fg="#4CAF50", selectbackground="#555")
        self.listbox_queue.pack(fill="x", padx=20)

        # Directory Selection
        dir_frame = tk.Frame(self.root, bg=self.bg_color)
        dir_frame.pack(fill="x", padx=20, pady=15)
        self.lbl_path = tk.Label(dir_frame, text=f"Save To: {self.download_dir}", font=("Arial", 9), bg=self.bg_color, fg="#aaa")
        self.lbl_path.pack(side="left")
        tk.Button(dir_frame, text="Change Folder", bg="#444", fg="white", command=self.browse_folder).pack(side="right")

        # Progress and Status
        self.progress_bar = ttk.Progressbar(self.root, orient="horizontal", mode="determinate", style="TProgressbar")
        self.progress_bar.pack(fill="x", padx=20, pady=10)
        
        self.lbl_status = tk.Label(self.root, text="স্ট্যাটাস: Ready", font=("Arial", 9), bg=self.bg_color, fg=self.fg_color)
        self.lbl_status.pack(padx=20, anchor="w")

        # Action Buttons
        btn_frame = tk.Frame(self.root, bg=self.bg_color)
        btn_frame.pack(pady=20)
        self.btn_start = tk.Button(btn_frame, text="Start Queue", bg="#28a745", fg="white", width=15, font=("Arial", 10, "bold"), command=self.start_queue_thread)
        self.btn_start.pack(side="left", padx=10, ipady=3)
        
        self.btn_stop = tk.Button(btn_frame, text="Stop / Pause", bg="#dc3545", fg="white", width=15, font=("Arial", 10, "bold"), command=self.stop_download)
        self.btn_stop.pack(side="left", padx=10, ipady=3)

    def browse_folder(self):
        selected_dir = filedialog.askdirectory(initialdir=self.download_dir)
        if selected_dir:
            self.download_dir = selected_dir
            self.lbl_path.config(text=f"Save To: {self.download_dir}")

    def check_clipboard(self):
        try:
            clipboard_content = pyperclip.paste()
            if clipboard_content != self.last_clipboard and clipboard_content.startswith("http"):
                self.last_clipboard = clipboard_content
                self.entry_url.delete(0, tk.END)
                self.entry_url.insert(0, clipboard_content)
        except:
            pass
        self.root.after(1000, self.check_clipboard) # Check every 1 second

    def add_to_queue(self):
        url = self.entry_url.get().strip()
        if url and url not in self.queue:
            self.queue.append(url)
            self.listbox_queue.insert(tk.END, url)
            self.entry_url.delete(0, tk.END)

    def stop_download(self):
        if self.is_downloading:
            self.cancel_download = True
            self.lbl_status.config(text="Stopping... (Will resume next time)", fg="#ffc107")

    def progress_hook(self, d):
        if self.cancel_download:
            raise Exception("Download stopped by user.")
            
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            if total > 0:
                percent = (d.get('downloaded_bytes', 0) / total) * 100
                self.progress_bar['value'] = percent
                speed = d.get('speed', 0)
                speed_str = f"{speed / (1024*1024):.2f} MB/s" if speed else "N/A"
                self.lbl_status.config(text=f"ডাউনলোড হচ্ছে: {percent:.1f}% | স্পিড: {speed_str}")
        elif d['status'] == 'finished':
            self.lbl_status.config(text="ফাইল প্রসেসিং চলছে...", fg="#17a2b8")

    def process_queue(self):
        self.is_downloading = True
        self.cancel_download = False

        while self.queue and not self.cancel_download:
            url = self.queue[0]
            self.lbl_status.config(text=f"ডাউনলোড শুরু হচ্ছে: {url[:30]}...", fg=self.fg_color)
            
            opts = {
                'outtmpl': os.path.join(self.download_dir, '%(title)s.%(ext)s'),
                'progress_hooks': [self.progress_hook],
                'format': 'best'
            }
            
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.download([url])
                
                # If successful, remove from queue
                self.queue.pop(0)
                self.listbox_queue.delete(0)
                self.progress_bar['value'] = 0
                
            except Exception as e:
                if str(e) == "Download stopped by user.":
                    break
                else:
                    self.lbl_status.config(text=f"ত্রুটি: {str(e)[:50]}", fg="red")
                    self.queue.pop(0)
                    self.listbox_queue.delete(0)

        self.is_downloading = False
        self.progress_bar['value'] = 0
        if self.cancel_download:
            self.lbl_status.config(text="ডাউনলোড পজ করা হয়েছে।", fg="#ffc107")
        elif not self.queue:
            self.lbl_status.config(text="কিউয়ের সব ডাউনলোড সম্পন্ন হয়েছে!", fg="#28a745")
            messagebox.showinfo("Success", "সব ডাউনলোড কমপ্লিট!")

    def start_queue_thread(self):
        if not self.queue:
            return messagebox.showwarning("Warning", "কিউতে কোনো লিংক নেই!")
        if not self.is_downloading:
            threading.Thread(target=self.process_queue, daemon=True).start()

if __name__ == "__main__":
    app_root = tk.Tk()
    AdvancedIDM(app_root)
    app_root.mainloop()
