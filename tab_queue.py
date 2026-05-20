import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import subprocess
import re
import os
import utils

class TabQueue(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.thread = None
        self.stop_flag = False
        self.last_was_progress = False
        self.current_process = None
        self._setup_ui()

    def _setup_ui(self):
        cfg_frame = ttk.LabelFrame(self, text="WSL Settings", padding=10)
        cfg_frame.pack(fill=tk.X, padx=10, pady=(10, 0))
        
        ttk.Label(cfg_frame, text="WSL Distro:").pack(side=tk.LEFT, padx=5)
        self.var_distro = tk.StringVar(value=self.app.config.get("wsl_distro", "Debian"))
        self.var_distro.trace_add("write", self.save_wsl_config)
        ttk.Entry(cfg_frame, textvariable=self.var_distro, width=15).pack(side=tk.LEFT, padx=5)
        
        ttk.Label(cfg_frame, text="EMSphInx Executable Dir (WSL Path):").pack(side=tk.LEFT, padx=(15, 5))
        self.var_wsl_dir = tk.StringVar(value=self.app.config.get("wsl_executable_dir", ""))
        self.var_wsl_dir.trace_add("write", self.save_wsl_config)
        ttk.Entry(cfg_frame, textvariable=self.var_wsl_dir, width=40).pack(side=tk.LEFT, padx=5)
        
        ttk.Button(cfg_frame, text="Configure Network Mounts", command=self.configure_mounts).pack(side=tk.RIGHT, padx=5)

        table_frame = ttk.LabelFrame(self, text="Indexing Queue", padding=10)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        columns = ("status", "scan", "nml")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=8)
        self.tree.heading("status", text="Status")
        self.tree.heading("scan", text="Scan Target")
        self.tree.heading("nml", text="NML File")
        self.tree.column("status", width=150, anchor=tk.CENTER)
        self.tree.column("scan", width=200)
        self.tree.column("nml", width=400)
        self.tree.pack(fill=tk.BOTH, expand=True)

        controls = ttk.Frame(self)
        controls.pack(fill=tk.X, padx=10, pady=5)
        
        self.btn_start = ttk.Button(controls, text="Start Queue", command=self.start_queue)
        self.btn_start.pack(side=tk.LEFT, padx=(20, 5))
        self.btn_stop = ttk.Button(controls, text="Stop", command=self.stop_queue, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, padx=5)
        
        ttk.Button(controls, text="Load Existing NML", command=self.load_existing_nml).pack(side=tk.RIGHT, padx=5)
        ttk.Button(controls, text="Clear Finished", command=self.clear_finished).pack(side=tk.RIGHT, padx=5)
        ttk.Button(controls, text="Remove Selected", command=self.remove_selected).pack(side=tk.RIGHT, padx=5)
        
        self.var_progress = tk.DoubleVar(value=0.0)
        self.progress_bar = ttk.Progressbar(controls, variable=self.var_progress, maximum=100)
        self.progress_bar.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(20, 5))
        self.lbl_queue_progress = ttk.Label(controls, text="Job 0 / 0", font=("Helvetica", 9, "bold"))
        self.lbl_queue_progress.pack(side=tk.RIGHT, padx=5)

        console_frame = ttk.LabelFrame(self, text="EMsoft Output Console", padding=10)
        console_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.txt_console = tk.Text(console_frame, bg="black", fg="lime green", height=10, state=tk.DISABLED)
        self.txt_console.pack(fill=tk.BOTH, expand=True)

    def save_wsl_config(self, *args):
        self.app.config["wsl_distro"] = self.var_distro.get()
        self.app.config["wsl_executable_dir"] = self.var_wsl_dir.get()
        utils.save_json(utils.CONFIG_FILE, self.app.config)

    def configure_mounts(self):
        top = tk.Toplevel(self.app.root)
        top.title("Network Mounts")
        top.geometry("600x300")
        top.transient(self.app.root)
        top.grab_set()
        
        ttk.Label(top, text="Map WSL Mount Points to Windows Network Shares", font=("Helvetica", 10, "bold")).pack(pady=10)
        
        cols = ("wsl", "win")
        tree = ttk.Treeview(top, columns=cols, show="headings", height=5)
        tree.heading("wsl", text="WSL Mount Point (e.g. /mnt/n)")
        tree.heading("win", text="Windows Share (e.g. \\\\server\\share)")
        tree.column("wsl", width=200)
        tree.column("win", width=350)
        tree.pack(fill=tk.BOTH, expand=True, padx=10)
        
        mounts = self.app.config.get("wsl_network_mounts", {})
        for wsl, win in mounts.items():
            tree.insert("", tk.END, values=(wsl, win))
            
        ctrl = ttk.Frame(top)
        ctrl.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(ctrl, text="WSL:").pack(side=tk.LEFT)
        var_wsl = tk.StringVar()
        ttk.Entry(ctrl, textvariable=var_wsl, width=15).pack(side=tk.LEFT, padx=5)
        
        ttk.Label(ctrl, text="Win:").pack(side=tk.LEFT)
        var_win = tk.StringVar()
        ttk.Entry(ctrl, textvariable=var_win, width=30).pack(side=tk.LEFT, padx=5)
        
        def add_mount():
            w = var_wsl.get().strip()
            v = var_win.get().strip()
            if w and v:
                tree.insert("", tk.END, values=(w, v))
                var_wsl.set("")
                var_win.set("")
        
        ttk.Button(ctrl, text="Add", command=add_mount).pack(side=tk.LEFT, padx=5)
        
        def remove_mount():
            sel = tree.selection()
            for s in sel:
                tree.delete(s)
                
        ttk.Button(ctrl, text="Remove Selected", command=remove_mount).pack(side=tk.LEFT, padx=5)
        
        def save():
            new_mounts = {}
            for item in tree.get_children():
                w, v = tree.item(item, "values")
                new_mounts[w] = v
            self.app.config["wsl_network_mounts"] = new_mounts
            utils.save_json(utils.CONFIG_FILE, self.app.config)
            top.destroy()
            
        btn_frame = ttk.Frame(top)
        btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text="Save & Close", command=save).pack()

    def add_job(self, scan_target, nml_path, status="Pending"):
        item_id = self.tree.insert("", tk.END, values=(status, scan_target, nml_path))
        self.update_global_progress_label()
        return item_id

    def load_existing_nml(self):
        filepath = filedialog.askopenfilename(filetypes=[("EMSphInx NML", "*.nml")])
        if not filepath:
            return
            
        try:
            with open(filepath, 'r') as f:
                content = f.read()
                
            mappings = self.app.config.get("wsl_drive_mappings", {})
            
            pat_match = re.search(r"patfile\s*=\s*'([^']+)'", content)
            master_match = re.search(r"masterfile\s*=\s*(.+?)(?:\n|!|$)", content)
            
            missing = []
            
            if pat_match:
                wsl_pat = pat_match.group(1)
                win_pat = utils.to_windows_path(wsl_pat, mappings)
                if not os.path.exists(win_pat):
                    missing.append(win_pat)
            else:
                messagebox.showerror("Error", "Could not find 'patfile' inside the NML.")
                return
                
            if master_match:
                master_raw = master_match.group(1)
                wsl_masters = re.findall(r"'([^']+)'", master_raw)
                for w_m in wsl_masters:
                    win_m = utils.to_windows_path(w_m, mappings)
                    if not os.path.exists(win_m):
                        sht_lib_dir = os.path.join(utils.SCRIPT_DIR, self.app.config.get("sht_library_dir", "SHT_Library"))
                        fallback_path = os.path.join(sht_lib_dir, os.path.basename(w_m))
                        if not os.path.exists(fallback_path):
                            missing.append(win_m)
            else:
                messagebox.showerror("Error", "Could not find 'masterfile' inside the NML.")
                return
                
            if missing:
                msg = "Cannot queue this job. The following files mapped in the NML do not exist on your local Windows drive:\n\n" + "\n".join(missing)
                messagebox.showerror("Missing Files", msg)
                return
                
            self.add_job(f"Loaded: {os.path.basename(filepath)}", filepath)
            messagebox.showinfo("Success", "Existing NML loaded and added to Queue.")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load NML:\n{e}")

    def update_global_progress_label(self):
        all_items = self.tree.get_children()
        total = len(all_items)
        if total == 0:
            self.lbl_queue_progress.config(text="Job 0 / 0")
            return
            
        completed = len([i for i in all_items if self.tree.item(i, "values")[0] in ["Done", "Failed"]])
        running = len([i for i in all_items if "Running" in self.tree.item(i, "values")[0]])
        
        current = completed + 1 if (running or completed < total) else completed
        if completed == total:
            current = total
            
        self.lbl_queue_progress.config(text=f"Job {current} / {total}")

    def append_console(self, text, is_progress=False):
        self.txt_console.config(state=tk.NORMAL)
        text_to_insert = text.strip()
        
        if is_progress and getattr(self, 'last_was_progress', False):
            self.txt_console.delete("end-2l", "end-1c")
            self.txt_console.insert(tk.END, text_to_insert + "\n")
        else:
            self.txt_console.insert(tk.END, text_to_insert + "\n")
            
        self.txt_console.see(tk.END)
        self.txt_console.config(state=tk.DISABLED)
        self.last_was_progress = is_progress

    def safe_tree_update(self, item, col, val):
        if self.tree.exists(item):
            self.tree.set(item, col, val)

    def update_progress(self, item, pct, text):
        self.safe_tree_update(item, "status", f"Running ({pct:.1f}%)")
        self.var_progress.set(pct)
        self.append_console(text, is_progress=True)

    def remove_selected(self):
        for selected in self.tree.selection():
            status = self.tree.item(selected, "values")[0]
            if "Running" in status:
                messagebox.showwarning("Warning", "Cannot remove a currently running job. Stop the queue first.")
            else:
                self.tree.delete(selected)
        self.update_global_progress_label()

    def clear_finished(self):
        for item in self.tree.get_children():
            if "Done" in self.tree.item(item, "values")[0] or "Failed" in self.tree.item(item, "values")[0]:
                self.tree.delete(item)
        self.update_global_progress_label()

    def stop_queue(self):
        self.stop_flag = True
        self.append_console("\n--- Stop Signal Sent. Waiting for current process to terminate... ---\n")

    def start_queue(self):
        if self.thread is None or not self.thread.is_alive():
            self.stop_flag = False
            self.btn_start.config(state=tk.DISABLED)
            self.btn_stop.config(state=tk.NORMAL)
            self.thread = threading.Thread(target=self._worker, daemon=True)
            self.thread.start()

    def check_and_mount_network_drives(self):
        distro = self.app.config.get("wsl_distro", "Debian")
        mounts = self.app.config.get("wsl_network_mounts", {})
        if not mounts:
            return True
            
        for mnt_point, win_share in mounts.items():
            if self.stop_flag: return False
            
            # Check if directory exists
            check_dir_cmd = f'wsl -d {distro} -u root -- bash -c "if [ ! -d \'{mnt_point}\' ]; then echo missing; fi"'
            res = subprocess.run(check_dir_cmd, shell=True, capture_output=True, text=True)
            if "missing" in res.stdout:
                mk_cmd = f'wsl -d {distro} -u root -- mkdir -p \'{mnt_point}\''
                subprocess.run(mk_cmd, shell=True, text=True)
                
            # Check if mounted
            check_mnt_cmd = f'wsl -d {distro} -- mount'
            res = subprocess.run(check_mnt_cmd, shell=True, capture_output=True, text=True)
            if f" {mnt_point} " not in res.stdout:
                self.app.root.after(0, self.append_console, f"\n--- Mounting network drive: {win_share} -> {mnt_point} ---\n", False)
                # Escape backslashes for bash/WSL argument passing
                win_share_esc = win_share.replace('\\', '\\\\')
                mnt_cmd = f'wsl -d {distro} -u root -- mount -t drvfs \'{win_share_esc}\' \'{mnt_point}\''
                mnt_res = subprocess.run(mnt_cmd, shell=True, capture_output=True, text=True)
                
                if mnt_res.returncode != 0:
                    err_msg = f"Mount Error:\n{mnt_res.stdout}\n{mnt_res.stderr}\n"
                    self.app.root.after(0, self.append_console, err_msg, False)
                    self.app.root.after(0, messagebox.showerror, "Mount Error", f"Failed to mount {win_share} to {mnt_point}.\nCheck console for details.")
                    return False
        return True

    def _worker(self):
        import time
        while not self.stop_flag:
            children = self.tree.get_children()
            pending_items = [item for item in children if self.tree.item(item, "values")[0] == "Pending"]
            
            if not pending_items:
                writing_items = [item for item in children if "Writing .up1" in self.tree.item(item, "values")[0]]
                if writing_items:
                    time.sleep(1)
                    continue
                else:
                    break
                
            item = pending_items[0]
            
            self.app.root.after(0, self.safe_tree_update, item, "status", "Running (0.0%)")
            self.app.root.after(0, self.var_progress.set, 0.0)
            self.app.root.after(0, self.update_global_progress_label)
            self.last_was_progress = False
            
            if not self.tree.exists(item): continue
            nml_path = self.tree.item(item, "values")[2]
            distro = self.app.config.get("wsl_distro", "Debian")
            wsl_exe_dir = self.app.config.get("wsl_executable_dir", "")
            wsl_nml_path = utils.to_wsl_path(nml_path, self.app.config.get("wsl_drive_mappings", {}))
            
            if not self.check_and_mount_network_drives():
                self.app.root.after(0, self.safe_tree_update, item, "status", "Failed (Mount Error)")
                self.app.root.after(0, self.append_console, "\n=== Job Aborted due to network mount failure ===\n", False)
                self.app.root.after(0, self.update_global_progress_label)
                continue
                
            cmd = f'wsl -d {distro} -- bash -c "cd \'{wsl_exe_dir}\' && ./IndexEBSD \'{wsl_nml_path}\'"'
            
            self.app.root.after(0, self.append_console, f"\n=== Starting Job ===\nCMD: {cmd}\n\n", False)
            
            self.current_process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, universal_newlines=True)
            
            for line in self.current_process.stdout:
                if self.stop_flag:
                    try:
                        self.current_process.kill()
                    except Exception:
                        pass
                    break
                
                line_clean = line.strip()
                if not line_clean: continue
                
                if "elapsed" in line_clean and "% complete" in line_clean:
                    m = re.search(r'([\d\.]+)%\s*complete', line_clean)
                    if m:
                        pct = float(m.group(1))
                        self.app.root.after(0, self.update_progress, item, pct, line_clean)
                    else:
                        self.app.root.after(0, self.append_console, line_clean, True)
                else:
                    self.app.root.after(0, self.append_console, line_clean, False)
            
            self.current_process.wait()
            self.current_process = None
            self.app.root.after(0, self.var_progress.set, 100.0)
            
            if self.stop_flag:
                self.app.root.after(0, self.safe_tree_update, item, "status", "Stopped")
            else:
                final_status = "Done" if getattr(self.current_process, 'returncode', -1) == 0 else "Failed"
                self.app.root.after(0, self.safe_tree_update, item, "status", final_status)
                self.app.root.after(0, self.append_console, f"\n=== Job {final_status} ===\n", False)
                
            self.app.root.after(0, self.update_global_progress_label)

        def reset_ui():
            self.btn_start.config(state=tk.NORMAL)
            self.btn_stop.config(state=tk.DISABLED)
            self.var_progress.set(0.0)
            if not self.stop_flag:
                self.append_console("\n--- Queue Completed ---\n", False)
                
        self.app.root.after(0, reset_ui)