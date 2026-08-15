import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
import json

# Fix HDF5 Network Drive Bugs (eoa = 2048 / Link Iteration Failed)
os.environ["HDF5_USE_FILE_LOCKING"] = "FALSE"

import utils
from tab_viewer_edax import TabViewerEdax
from tab_nml_edax import TabNMLBuilderEdax
from tab_viewer_oxford import TabViewerOxford
from tab_nml_oxford import TabNMLOxford
from tab_queue import TabQueue
from help_dialog import HelpDialog

class EMSphInxGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("EMSphInx Studio")
        self.root.geometry("1300x800")

        # Intercept close so native/WSL jobs and partial UP1 writes are stopped safely.
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        try:
            self.root.state('zoomed')
        except tk.TclError:
            try:
                self.root.attributes('-zoomed', True)
            except tk.TclError:
                pass 
        
        self.initialize_config()
        if not utils.uses_wsl() and not self.config.get("native_executable_dir", "").strip():
            messagebox.showinfo(
                "First Time Setup",
                f"Select the folder containing the {utils.execution_backend_name()} IndexEBSD executable.",
            )
            self.configure_execution(is_first_setup=True)
        self.params = utils.load_params()
        
        sht_dir_abs = os.path.abspath(os.path.join(utils.SCRIPT_DIR, self.config.get("sht_library_dir", "SHT_Library")))
        if ' ' in sht_dir_abs:
            messagebox.showwarning("Space in Path Warning",
                f"The SHT Library directory path contains spaces:\n{sht_dir_abs}\n\n"
                "EMSphInx will fail to read multiple master patterns if the path contains spaces. "
                "Consider moving this application to a path without spaces.")

        self.shared_state = utils.SharedState()
        self._setup_ui()

    def initialize_config(self):
        user = utils.get_current_user()
        has_default = os.path.exists(utils.DEFAULT_CONFIG_FILE)
        has_user_config = False
        
        app_config_data = {}
        if os.path.exists(utils.CONFIG_FILE):
            try:
                with open(utils.CONFIG_FILE, 'r') as f:
                    app_config_data = json.load(f)
                
                if app_config_data and "wsl_distro" in app_config_data:
                    # Move top-level keys into the current user's profile instead of wiping the file
                    top_level_keys = ["wsl_distro", "wsl_executable_dir", "native_executable_dir", "sht_library_dir", "wsl_drive_mappings", "wsl_network_mounts", "wsl_sudo_password"]
                    user_config = {}
                    for k in top_level_keys:
                        if k in app_config_data:
                            user_config[k] = app_config_data.pop(k)
                            
                    # If this is the very first migration or an old version dumped top-level keys,
                    # we assign them to the current user, keeping other users safe!
                    app_config_data[user] = user_config
                    utils.save_json(utils.CONFIG_FILE, app_config_data)
                    
                if user in app_config_data:
                    has_user_config = True
            except Exception:
                pass
                
        if has_default and not has_user_config:
            try:
                with open(utils.DEFAULT_CONFIG_FILE, 'r') as f:
                    def_config = json.load(f)
            except Exception as e:
                messagebox.showerror("Configuration Error", f"Failed to parse {utils.DEFAULT_CONFIG_FILE}. If you manually edited it, please fix any syntax errors.\n\n{e}")
                return
                
            app_config_data[user] = def_config.copy()
            if "wsl_drive_mappings" not in app_config_data[user] or not app_config_data[user]["wsl_drive_mappings"]:
                app_config_data[user]["wsl_drive_mappings"] = utils.get_local_drives()
            utils.save_json(utils.CONFIG_FILE, app_config_data)
            self.config = app_config_data[user]
            return
            
        if not has_default and not has_user_config:
            messagebox.showinfo("First Time Setup", f"Welcome! No configuration found.\nPlease configure EMSphInx for {utils.execution_backend_name()} before proceeding.")
            
            temp_config = utils.DEFAULT_CONFIG.copy()
            
            # Auto-detect both local and network mapped drives
            net_mappings, net_mounts = utils.get_network_drives()
            local_drives = utils.get_local_drives()
            
            temp_config["wsl_drive_mappings"] = {**local_drives, **net_mappings}
            temp_config["wsl_network_mounts"] = net_mounts
            
            self.config = temp_config
            
            self.configure_execution(is_first_setup=True)
            return

        self.config = app_config_data[user]
        for key, value in utils.DEFAULT_CONFIG.items():
            self.config.setdefault(key, value.copy() if isinstance(value, dict) else value)

    def _setup_ui(self):
        # Create Menu Bar
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="EMSphInx Studio Help", command=self.show_help)

        settings_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Settings", menu=settings_menu)
        settings_menu.add_command(label=f"EMSphInx Configuration ({utils.execution_backend_name()})", command=self.configure_execution)

        header = ttk.Frame(self.root, padding=10)
        header.pack(fill=tk.X)
        
        ttk.Label(header, text="System Mode:", font=("Helvetica", 12, "bold")).pack(side=tk.LEFT, padx=(0, 10))
        
        self.var_mode = tk.StringVar(value=self.params.get("system_mode", "EDAX"))
        rb_edax = ttk.Radiobutton(header, text="EDAX (.up1 / .edaxh5)", variable=self.var_mode, value="EDAX", command=self.switch_mode)
        rb_edax.pack(side=tk.LEFT, padx=5)
        
        rb_oxford = ttk.Radiobutton(header, text="Oxford (.h5oina)", variable=self.var_mode, value="OXFORD", command=self.switch_mode)
        rb_oxford.pack(side=tk.LEFT, padx=5)

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # Instantiate all tabs (Modularized)
        self.tab_viewer_edax = TabViewerEdax(self.notebook, self)
        self.tab_nml_edax = TabNMLBuilderEdax(self.notebook, self)
        
        self.tab_viewer_oxford = TabViewerOxford(self.notebook, self)
        self.tab_nml_oxford = TabNMLOxford(self.notebook, self)
        
        self.tab_queue = TabQueue(self.notebook, self)
        # Initialize default view (EDAX)
        self.switch_mode()

    def switch_mode(self, *args):
        mode = self.var_mode.get()
        
        # Clear existing tabs
        for tab in self.notebook.tabs():
            self.notebook.forget(tab)
            
        if mode == "EDAX":
            self.notebook.add(self.tab_viewer_edax, text=" 🟥 EDAX Pattern Viewer ")
            self.notebook.add(self.tab_nml_edax, text=" 🟥 EDAX NML Builder ")
        else:
            self.notebook.add(self.tab_viewer_oxford, text=" 🔵 Oxford Map Viewer ")
            self.notebook.add(self.tab_nml_oxford, text=" 🔵 Oxford NML Builder ")
            
        self.params["system_mode"] = mode
        utils.save_json(utils.PARAMS_FILE, self.params)
            
        # Re-add Queue tab (Never unloads)
        self.notebook.add(self.tab_queue, text=" Job Queue & Execution ")

    def on_closing(self):
        """Handle application close without orphaned jobs or partial UP1 files."""
        is_queue_running = self.tab_queue.thread and self.tab_queue.thread.is_alive()
        is_up1_writing = bool(self.shared_state.up1_tasks)
        
        if is_queue_running or is_up1_writing:
            msg = "Background tasks are currently running (Queue or UP1 Generation).\n\nDo you want to abort them and exit the application?"
            if messagebox.askokcancel("Running Tasks Detected", msg):
                self.tab_queue.stop_flag = True
                self.tab_queue.terminate_current_process()
                
                # Wait briefly to let UP1 writer threads catch the flag, clean up partial files, and exit
                if is_up1_writing:
                    import time
                    for _ in range(10):  # Wait up to 2 seconds
                        if not self.shared_state.up1_tasks:
                            break
                        time.sleep(0.2)
                    
                self.root.destroy()
        else:
            self.root.destroy()

    def show_help(self):
        HelpDialog(self.root)

    def configure_execution(self, is_first_setup=False):
        if utils.uses_wsl():
            self.configure_wsl(is_first_setup=is_first_setup)
        else:
            self.configure_native(is_first_setup=is_first_setup)

    def configure_native(self, is_first_setup=False):
        top = tk.Toplevel(self.root)
        top.title(f"EMSphInx Configuration ({utils.execution_backend_name()})")
        top.geometry("700x190")
        top.resizable(True, False)
        top.transient(self.root)
        top.grab_set()

        frame = ttk.LabelFrame(top, text="Native execution", padding=12)
        frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)
        ttk.Label(
            frame,
            text="Folder containing the compiled IndexEBSD executable:",
        ).grid(row=0, column=0, columnspan=3, sticky=tk.W, pady=(0, 8))

        var_native_dir = tk.StringVar(value=self.config.get("native_executable_dir", ""))
        entry = ttk.Entry(frame, textvariable=var_native_dir, width=70)
        entry.grid(row=1, column=0, sticky=tk.EW, padx=(0, 8))

        def browse():
            selected = filedialog.askdirectory(
                parent=top,
                initialdir=var_native_dir.get() or os.getcwd(),
                title="Select the folder containing IndexEBSD",
            )
            if selected:
                var_native_dir.set(selected)

        ttk.Button(frame, text="Browse…", command=browse).grid(row=1, column=1)
        ttk.Label(
            frame,
            text="Data, NML, SHT, and output paths are passed directly as native paths.",
        ).grid(row=2, column=0, columnspan=3, sticky=tk.W, pady=(8, 12))
        frame.columnconfigure(0, weight=1)

        def save():
            selected_dir = os.path.abspath(os.path.expanduser(var_native_dir.get().strip())) if var_native_dir.get().strip() else ""
            self.config["native_executable_dir"] = selected_dir
            if selected_dir:
                config_error = utils.validate_execution_config(self.config)
                if config_error:
                    messagebox.showerror("EMSphInx Configuration", config_error, parent=top)
                    return
            user = utils.get_current_user()
            data = {}
            if os.path.exists(utils.CONFIG_FILE):
                try:
                    with open(utils.CONFIG_FILE, "r") as f:
                        data = json.load(f)
                except Exception as e:
                    messagebox.showerror("Configuration Error", f"Failed to parse {utils.CONFIG_FILE}.\n\n{e}", parent=top)
                    return
            data[user] = self.config
            utils.save_json(utils.CONFIG_FILE, data)
            top.destroy()

        ttk.Button(frame, text="Save & Close", command=save).grid(row=3, column=0, columnspan=2)
        if is_first_setup:
            top.protocol("WM_DELETE_WINDOW", save)
            self.root.wait_window(top)

    def configure_wsl(self, is_first_setup=False):
        top = tk.Toplevel(self.root)
        top.title("WSL Configuration & Mounts")
        top.geometry("600x450")
        top.transient(self.root)
        top.grab_set()

        cfg_frame = ttk.LabelFrame(top, text="WSL Settings", padding=10)
        cfg_frame.pack(fill=tk.X, padx=10, pady=(10, 0))
        
        ttk.Label(cfg_frame, text="WSL Distro:").pack(side=tk.LEFT, padx=5)
        var_distro = tk.StringVar(value=self.config.get("wsl_distro", "Debian"))
        ttk.Entry(cfg_frame, textvariable=var_distro, width=15).pack(side=tk.LEFT, padx=5)
        
        ttk.Label(cfg_frame, text="EMSphInx Executable Dir (WSL Path):").pack(side=tk.LEFT, padx=(15, 5))
        var_wsl_dir = tk.StringVar(value=self.config.get("wsl_executable_dir", ""))
        ttk.Entry(cfg_frame, textvariable=var_wsl_dir, width=30).pack(side=tk.LEFT, padx=5)
        
        notebook = ttk.Notebook(top)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # --- Network Mounts Tab ---
        frame_net = ttk.Frame(notebook)
        notebook.add(frame_net, text="Network Mounts")
        
        ttk.Label(frame_net, text="Mount UNC network paths to WSL (e.g. \\\\server\\share -> /mnt/n)", font=("Helvetica", 9)).pack(pady=5)
        
        cols_net = ("wsl", "win")
        tree_net = ttk.Treeview(frame_net, columns=cols_net, show="headings", height=5)
        tree_net.heading("wsl", text="WSL Mount Point")
        tree_net.heading("win", text="Windows UNC Path")
        tree_net.column("wsl", width=150)
        tree_net.column("win", width=350)
        tree_net.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        mounts = self.config.get("wsl_network_mounts", {})
        for wsl, win in mounts.items():
            tree_net.insert("", tk.END, values=(wsl, win))
            
        ctrl_net = ttk.Frame(frame_net)
        ctrl_net.pack(fill=tk.X, padx=5, pady=5)
        
        ttk.Label(ctrl_net, text="WSL:").pack(side=tk.LEFT)
        var_wsl_net = tk.StringVar()
        ttk.Entry(ctrl_net, textvariable=var_wsl_net, width=15).pack(side=tk.LEFT, padx=5)
        
        ttk.Label(ctrl_net, text="Win UNC:").pack(side=tk.LEFT)
        var_win_net = tk.StringVar()
        ttk.Entry(ctrl_net, textvariable=var_win_net, width=30).pack(side=tk.LEFT, padx=5)
        
        def add_mount():
            w = var_wsl_net.get().strip()
            v = var_win_net.get().strip()
            if w and v:
                tree_net.insert("", tk.END, values=(w, v))
                var_wsl_net.set("")
                var_win_net.set("")
        
        ttk.Button(ctrl_net, text="Add", command=add_mount).pack(side=tk.LEFT, padx=5)
        
        def remove_mount():
            for s in tree_net.selection():
                tree_net.delete(s)
                
        ttk.Button(ctrl_net, text="Remove Selected", command=remove_mount).pack(side=tk.LEFT, padx=5)
        
        # --- Drive Mappings Tab ---
        frame_drive = ttk.Frame(notebook)
        notebook.add(frame_drive, text="Drive Mappings")
        
        ttk.Label(frame_drive, text="String replacement for drive letters (e.g. C: -> /mnt/c)", font=("Helvetica", 9)).pack(pady=5)
        
        cols_drive = ("win", "wsl")
        tree_drive = ttk.Treeview(frame_drive, columns=cols_drive, show="headings", height=5)
        tree_drive.heading("win", text="Windows Drive Letter")
        tree_drive.heading("wsl", text="WSL Path Equivalent")
        tree_drive.column("win", width=150)
        tree_drive.column("wsl", width=350)
        tree_drive.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        mappings = self.config.get("wsl_drive_mappings", {})
        for win_drive, wsl_path in mappings.items():
            tree_drive.insert("", tk.END, values=(win_drive, wsl_path))
            
        ctrl_drive = ttk.Frame(frame_drive)
        ctrl_drive.pack(fill=tk.X, padx=5, pady=5)
        
        ttk.Label(ctrl_drive, text="Drive (X:):").pack(side=tk.LEFT)
        var_win_drive = tk.StringVar()
        ttk.Entry(ctrl_drive, textvariable=var_win_drive, width=10).pack(side=tk.LEFT, padx=5)
        
        ttk.Label(ctrl_drive, text="WSL Path:").pack(side=tk.LEFT)
        var_wsl_drive = tk.StringVar()
        ttk.Entry(ctrl_drive, textvariable=var_wsl_drive, width=25).pack(side=tk.LEFT, padx=5)
        
        def add_mapping():
            w = var_win_drive.get().strip().upper()
            v = var_wsl_drive.get().strip()
            if w and v:
                if not w.endswith(':'): w += ':'
                tree_drive.insert("", tk.END, values=(w, v))
                var_win_drive.set("")
                var_wsl_drive.set("")
        
        ttk.Button(ctrl_drive, text="Add", command=add_mapping).pack(side=tk.LEFT, padx=5)
        
        def remove_mapping():
            for s in tree_drive.selection():
                tree_drive.delete(s)
                
        ttk.Button(ctrl_drive, text="Remove Selected", command=remove_mapping).pack(side=tk.LEFT, padx=5)
        
        def save():
            new_mounts = {}
            for item in tree_net.get_children():
                w, v = tree_net.item(item, "values")
                new_mounts[w] = v
                
            new_mappings = {}
            for item in tree_drive.get_children():
                w, v = tree_drive.item(item, "values")
                new_mappings[w] = v
                
            self.config["wsl_distro"] = var_distro.get()
            self.config["wsl_executable_dir"] = var_wsl_dir.get()
            self.config["wsl_network_mounts"] = new_mounts
            self.config["wsl_drive_mappings"] = new_mappings
            if is_first_setup or var_update_default.get():
                utils.save_json(utils.DEFAULT_CONFIG_FILE, self.config)
                
            user = utils.get_current_user()
            data = {}
            if os.path.exists(utils.CONFIG_FILE):
                try:
                    with open(utils.CONFIG_FILE, 'r') as f:
                        data = json.load(f)
                except Exception as e:
                    messagebox.showerror("Configuration Error", f"Failed to parse {utils.CONFIG_FILE}. If you manually edited it, please fix any syntax errors before saving.\n\n{e}")
                    return
            data[user] = self.config
            utils.save_json(utils.CONFIG_FILE, data)
            
            top.destroy()
        def redetect_drives():
            net_mappings, net_mounts = utils.get_network_drives()
            local_drives = utils.get_local_drives()
            all_mappings = {**local_drives, **net_mappings}
            
            for s in tree_net.get_children(): tree_net.delete(s)
            for s in tree_drive.get_children(): tree_drive.delete(s)
                
            for wsl, win in net_mounts.items():
                tree_net.insert("", tk.END, values=(wsl, win))
            for win_drive, wsl_path in all_mappings.items():
                tree_drive.insert("", tk.END, values=(win_drive, wsl_path))
                
        btn_frame = ttk.Frame(top)
        btn_frame.pack(pady=10)
        
        ttk.Button(btn_frame, text="Redetect All Mapped Drives", command=redetect_drives).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Save & Close", command=save).pack(side=tk.LEFT, padx=5)
        
        var_update_default = tk.BooleanVar(value=is_first_setup)
        if not is_first_setup:
            ttk.Checkbutton(top, text="Save as default for all new users (updates default_app_config.json)", variable=var_update_default).pack(pady=(0, 10))

        if is_first_setup:
            top.protocol("WM_DELETE_WINDOW", save)
            self.root.wait_window(top)

if __name__ == "__main__":
    root = tk.Tk()
    style = ttk.Style()
    if 'clam' in style.theme_names():
        style.theme_use('clam')
    app = EMSphInxGUI(root)
    root.mainloop()
