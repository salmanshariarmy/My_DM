import tkinter as tk
import os
from engine import DownloadEngine
from ui import IDM_UI

if __name__ == "__main__":
    # Create Default Download Directory
    default_dir = os.path.join(os.path.expanduser("~"), "Downloads", "My_DM_Downloads")
    if not os.path.exists(default_dir):
        os.makedirs(default_dir)

    # Initialize Engine and UI
    root = tk.Tk()
    
    dl_engine = DownloadEngine(download_dir=default_dir)
    app = IDM_UI(root=root, engine=dl_engine)
    
    root.mainloop()
