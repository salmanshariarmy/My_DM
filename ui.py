def show_pre_download_dialog(self, url, fname, size):
        dlg = tk.Toplevel(self.root)
        dlg.title("Download File Info")
        dlg.geometry("550x250")
        dlg.configure(bg="#252526")
        
        # URL Section
        url_frame = tk.Frame(dlg, bg="#252526")
        url_frame.pack(fill="x", padx=20, pady=(30, 10))
        tk.Label(url_frame, text="URL:", bg="#252526", fg="white", width=8, anchor="w").pack(side="left")
        
        url_entry = tk.Entry(url_frame, bg="#333333", fg="#aaaaaa", relief="flat")
        url_entry.insert(0, url)
        url_entry.config(state="readonly")
        url_entry.pack(side="left", fill="x", expand=True)
        
        # Save As Section
        save_frame = tk.Frame(dlg, bg="#252526")
        save_frame.pack(fill="x", padx=20, pady=10)
        tk.Label(save_frame, text="Save As:", bg="#252526", fg="white", width=8, anchor="w").pack(side="left")
        
        path = tk.Entry(save_frame, bg="white", fg="black")
        default_path = os.path.join(self.engine.base_dir, self.engine.get_category_folder(fname), fname)
        path.insert(0, default_path)
        path.pack(side="left", fill="x", expand=True)
        
        # Button Section
        def start():
            item_id = f"task_{self.item_counter}"
            self.item_counter += 1
            size_str = f"{size/(1024*1024):.2f} MB" if size > 0 else "Unknown"
            
            tree_item = self.tree.insert("", "end", iid=item_id, values=(fname, size_str, "Connecting...", "-", "-", url))
            self.tasks[item_id] = {'url': url, 'filename': fname, 'size': size}
            
            self.dialogs[item_id] = DownloadProgressDialog(self.root, fname, size)
            self.engine.start_download(item_id, url, fname, self.progress_cb, self.finish_cb, self.error_cb)
            dlg.destroy()
            
        tk.Button(dlg, text="Start Download", bg="#007acc", fg="white", font=("Arial", 10, "bold"), padx=15, pady=5, command=start).pack(pady=30)
