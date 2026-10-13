import tkinter as tk
import os
from engine import DownloadEngine
from ui import IDM_UI

if __name__ == "__main__":
    # Create Default Download Directory
    user_home = os.path.expanduser("~")
    base_download_dir = os.path.join(user_home, "Downloads", "My_IDM_Downloads")
    os.makedirs(base_download_dir, exist_ok=True)

    # Initialize Engine and UI
    root = tk.Tk()
    
    # Connect Engine with UI
    dl_engine = DownloadEngine(base_dir=base_download_dir)
    app = IDM_UI(root=root, engine=dl_engine)
    
    # Run App
    root.mainloop()
