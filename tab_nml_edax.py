import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
import urllib.request
import urllib.parse
import json
import re
import shutil
import utils
import webbrowser
import threading

class TabNMLBuilderEdax(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.state = app.shared_state
        self._is_updating_ui = False
        self._setup_ui()

    def _setup_ui(self):
        ttk.Label(self, text="EDAX: EMsoft NML Generator", font=("Helvetica", 14, "bold")).pack(pady=(20, 10))
        
        scroll = utils.ScrollableFrame(self)
        scroll.pack(fill=tk.BOTH, expand=True)
        
        content = ttk.Frame(scroll.scrollable_frame)
        content.pack(fill=tk.BOTH, expand=True, padx=40, pady=(0, 20))

        dir_frame = ttk.Frame(content)
        dir_frame.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(dir_frame, text="Working Directory:", font=("Helvetica", 10, "bold")).pack(side=tk.LEFT)
        self.var_work_dir = tk.StringVar(value="Not set (Load H5 file in Tab 1)")
        ttk.Entry(dir_frame, textvariable=self.var_work_dir, state="readonly").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 0))

        # 1. Master Pattern Downloader Shell
        sht_frame = ttk.LabelFrame(content, text="Master Pattern (.sht)", padding=10)
        sht_frame.pack(fill=tk.X, pady=(0, 15))
        
        ttk.Label(sht_frame, text="Element:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.var_element = tk.StringVar(value="Cu")
        ttk.Entry(sht_frame, textvariable=self.var_element, width=8).grid(row=0, column=1, padx=(5, 15))
        
        ttk.Label(sht_frame, text="Structure:").grid(row=0, column=2, sticky=tk.W, pady=5)
        self.var_struct = tk.StringVar(value="[A1]")
        self.combo_struct = ttk.Combobox(sht_frame, textvariable=self.var_struct, width=8)
        self.combo_struct.grid(row=0, column=3, padx=(5, 5))
        
        ttk.Button(sht_frame, text="Load Structures", command=self.load_structures).grid(row=0, column=4, padx=(0, 15))

        ttk.Label(sht_frame, text="kV:").grid(row=0, column=5, sticky=tk.W, pady=5)
        self.var_kv = tk.StringVar(value="30")
        ttk.Entry(sht_frame, textvariable=self.var_kv, width=8).grid(row=0, column=6, padx=(5, 15))

        self.btn_fetch_sht = ttk.Button(sht_frame, text="Find/Fetch", command=self.fetch_sht)
        self.btn_fetch_sht.grid(row=0, column=7, padx=(5, 0))
        
        ttk.Button(sht_frame, text="Open SHT Database in Browser", command=lambda: webbrowser.open("https://github.com/EMsoft-org/SHTdatabase/tree/master")).grid(row=0, column=8, padx=(5, 0))

        ttk.Label(sht_frame, text="Master Pattern(s):").grid(row=1, column=0, sticky=tk.NW, pady=(10, 5))
        
        list_frame = ttk.Frame(sht_frame)
        list_frame.grid(row=1, column=1, columnspan=5, sticky=tk.NSEW, padx=(5, 15), pady=(10, 5))
        
        self.sht_listbox = tk.Listbox(list_frame, height=4, selectmode=tk.EXTENDED)
        yscroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.sht_listbox.yview)
        xscroll = ttk.Scrollbar(list_frame, orient=tk.HORIZONTAL, command=self.sht_listbox.xview)
        
        self.sht_listbox.grid(row=0, column=0, sticky=tk.NSEW)
        yscroll.grid(row=0, column=1, sticky=tk.NS)
        xscroll.grid(row=1, column=0, sticky=tk.EW)
        
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)
        self.sht_listbox.config(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        
        btn_frame_sht = ttk.Frame(sht_frame)
        btn_frame_sht.grid(row=1, column=7, columnspan=2, sticky=tk.NW, pady=(10, 5))
        ttk.Button(btn_frame_sht, text="Browse", command=self.browse_sht).pack(fill=tk.X, pady=(0, 2))
        ttk.Button(btn_frame_sht, text="Remove", command=self.remove_sht).pack(fill=tk.X)

        self.lbl_sht_status = ttk.Label(sht_frame, text="No .sht file selected or fetched.", foreground="blue")
        self.lbl_sht_status.grid(row=2, column=0, columnspan=7, sticky=tk.W, pady=(10, 0))

        # 2. Grid parameters 
        params_frame = ttk.LabelFrame(content, text="Spherical Indexing Parameters", padding=10)
        params_frame.pack(fill=tk.X, pady=10)
        
        ttk.Label(params_frame, text="Calculated Binning:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.lbl_binning = ttk.Label(params_frame, text="Unknown (Load UP1 first)", foreground="gray")
        self.lbl_binning.grid(row=0, column=1, sticky=tk.W, padx=10)

        ttk.Label(params_frame, text="Native Delta:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.var_delta = tk.StringVar(value=str(self.app.params.get("EDAX", {}).get("native_delta", 23.0)))
        ttk.Entry(params_frame, textvariable=self.var_delta, width=10).grid(row=1, column=1, sticky=tk.W, padx=10)

        ttk.Label(params_frame, text="Bandwidth:").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.var_bw = tk.StringVar(value=str(self.app.params.get("EDAX", {}).get("bw", 123)))
        self.var_bw.trace_add("write", self.on_bw_change)
        ttk.Entry(params_frame, textvariable=self.var_bw, width=10).grid(row=2, column=1, sticky=tk.W, padx=10)
        
        bw_hint = "Recommended: 53, 63, 68, 74, 88, 95, 113, 122, 123, 158, 172, 188, 203, 221, 263, 284, 313"
        ttk.Label(params_frame, text=bw_hint, foreground="gray", font=("Helvetica", 8)).grid(row=2, column=2, sticky=tk.W, padx=10)

        ttk.Label(params_frame, text="Circular Mask (circmask):").grid(row=3, column=0, sticky=tk.W, pady=5)
        self.var_circmask = tk.StringVar(value="0 (Enabled)")
        self.combo_circmask = ttk.Combobox(params_frame, textvariable=self.var_circmask, values=["0 (Enabled)", "-1 (Disabled)"], state="readonly", width=15)
        self.combo_circmask.grid(row=3, column=1, sticky=tk.W, padx=10)

        self.var_gausbckg = tk.BooleanVar(value=self.app.params.get("EDAX", {}).get("gausbckg", True))
        self.var_gausbckg.trace_add("write", self.on_gaus_change)
        ttk.Checkbutton(params_frame, text="Apply Gaussian Background (gausbckg)", variable=self.var_gausbckg).grid(row=4, column=0, columnspan=2, sticky=tk.W, pady=(10, 5))
        
        ttk.Label(params_frame, text="NRegions:").grid(row=5, column=0, sticky=tk.W, pady=5)
        self.var_nregions = tk.StringVar(value=str(self.app.params.get("EDAX", {}).get("nregions", 10)))
        self.entry_nregions = ttk.Entry(params_frame, textvariable=self.var_nregions, width=10)
        self.entry_nregions.grid(row=5, column=1, sticky=tk.W, padx=10)
        
        hint_nregions = "(10 is a decent value. Adjust based on relative size of Kikuchi bands to pattern size, this depends on detector distance)"
        ttk.Label(params_frame, text=hint_nregions, foreground="gray", font=("Helvetica", 8)).grid(row=5, column=2, sticky=tk.W, padx=10)
        self.on_gaus_change()

        ttk.Label(params_frame, text="Threads (nthread):").grid(row=6, column=0, sticky=tk.W, pady=5)
        self.var_nthread = tk.StringVar(value=str(self.app.params.get("EDAX", {}).get("nthread", 0)))
        ttk.Entry(params_frame, textvariable=self.var_nthread, width=10).grid(row=6, column=1, sticky=tk.W, padx=10)
        
        ttk.Label(params_frame, text="Batch Size (batchsize):").grid(row=7, column=0, sticky=tk.W, pady=5)
        self.var_batchsize = tk.StringVar(value=str(self.app.params.get("EDAX", {}).get("batchsize", 0)))
        ttk.Entry(params_frame, textvariable=self.var_batchsize, width=10).grid(row=7, column=1, sticky=tk.W, padx=10)
        
        max_cpu = os.cpu_count() or "Unknown"
        ttk.Label(params_frame, text=f"(0 = use maximum available threads. Detected: {max_cpu} logical cores)", foreground="gray", font=("Helvetica", 8)).grid(row=6, column=2, sticky=tk.W, padx=10)

        ttk.Button(params_frame, text="Reset to Defaults", command=self.reset_defaults).grid(row=8, column=0, pady=(10, 0), sticky=tk.W)

        # 3. ROI Frame
        roi_frame = ttk.LabelFrame(content, text="Region of Interest (ROI) [Syncs with Tab 1 map]", padding=10)
        roi_frame.pack(fill=tk.X, pady=10)
        
        self.var_use_roi = tk.BooleanVar(value=False)
        self.var_use_roi.trace_add("write", self.on_roi_manual_edit)
        ttk.Checkbutton(roi_frame, text="Enable ROI Masking", variable=self.var_use_roi).grid(row=0, column=0, columnspan=3, sticky=tk.W, pady=(0, 5))

        self.lbl_roi_max = ttk.Label(roi_frame, text="Max Bounds: X=0, Y=0", foreground="gray", font=("Helvetica", 9, "italic"))
        self.lbl_roi_max.grid(row=0, column=4, columnspan=4, sticky=tk.W, pady=(0, 5))

        ttk.Label(roi_frame, text="X0:").grid(row=1, column=0, sticky=tk.E, padx=5)
        self.var_roi_x0 = tk.StringVar(value="0")
        self.var_roi_x0.trace_add("write", self.on_roi_manual_edit)
        ttk.Entry(roi_frame, textvariable=self.var_roi_x0, width=8).grid(row=1, column=1)

        ttk.Label(roi_frame, text="Y0:").grid(row=1, column=2, sticky=tk.E, padx=5)
        self.var_roi_y0 = tk.StringVar(value="0")
        self.var_roi_y0.trace_add("write", self.on_roi_manual_edit)
        ttk.Entry(roi_frame, textvariable=self.var_roi_y0, width=8).grid(row=1, column=3)

        ttk.Label(roi_frame, text="Width (dx):").grid(row=1, column=4, sticky=tk.E, padx=5)
        self.var_roi_w = tk.StringVar(value="0")
        self.var_roi_w.trace_add("write", self.on_roi_manual_edit)
        ttk.Entry(roi_frame, textvariable=self.var_roi_w, width=8).grid(row=1, column=5)

        ttk.Label(roi_frame, text="Height (dy):").grid(row=1, column=6, sticky=tk.E, padx=5)
        self.var_roi_h = tk.StringVar(value="0")
        self.var_roi_h.trace_add("write", self.on_roi_manual_edit)
        ttk.Entry(roi_frame, textvariable=self.var_roi_h, width=8).grid(row=1, column=7)

        # 4. Output NML Name
        output_frame = ttk.LabelFrame(content, text="Output NML", padding=10)
        output_frame.pack(fill=tk.X, pady=10)
        ttk.Label(output_frame, text="File Name:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.var_nml_name = tk.StringVar()
        ttk.Entry(output_frame, textvariable=self.var_nml_name, width=60).grid(row=0, column=1, sticky=tk.W, padx=10)

        # Action Buttons
        btn_frame = ttk.Frame(content)
        btn_frame.pack(fill=tk.X, pady=20)
        
        self.btn_queue = ttk.Button(btn_frame, text="Generate NML & Add to Queue", command=self.generate_and_queue)
        self.btn_queue.pack(side=tk.RIGHT)

    def _append_sht_path(self, new_path):
        existing = self.sht_listbox.get(0, tk.END)
        if new_path not in existing:
            self.sht_listbox.insert(tk.END, new_path)

    def remove_sht(self):
        selected_indices = self.sht_listbox.curselection()
        for i in reversed(selected_indices):
            self.sht_listbox.delete(i)
        if self.sht_listbox.size() == 0:
            self.lbl_sht_status.config(text="No .sht file selected or fetched.", foreground="blue")
        else:
            self.lbl_sht_status.config(text=f"Total: {self.sht_listbox.size()} file(s) in list.", foreground="green")

    def on_roi_manual_edit(self, *args):
        if self._is_updating_ui: return
        if not self.var_use_roi.get():
            self.state.use_roi = False
            if hasattr(self.app, 'tab_viewer_edax'):
                self.app.tab_viewer_edax.draw_roi_from_state()
            return
        try:
            rx = int(self.var_roi_x0.get() or 0)
            ry = int(self.var_roi_y0.get() or 0)
            rw = int(self.var_roi_w.get() or 0)
            rh = int(self.var_roi_h.get() or 0)
            self.state.roi = (rx, ry, rw, rh)
            self.state.use_roi = True
            if hasattr(self.app, 'tab_viewer_edax'):
                self.app.tab_viewer_edax.draw_roi_from_state()
        except ValueError:
            pass 

    def update_roi_ui(self):
        self._is_updating_ui = True
        if self.state.use_roi:
            self.var_use_roi.set(True)
            x0, y0, w, h = self.state.roi
            self.var_roi_x0.set(str(x0))
            self.var_roi_y0.set(str(y0))
            self.var_roi_w.set(str(w))
            self.var_roi_h.set(str(h))
        else:
            self.var_use_roi.set(False)
        self._is_updating_ui = False

    def on_gaus_change(self, *args):
        if self.var_gausbckg.get():
            self.entry_nregions.config(state=tk.NORMAL)
            if self.var_nregions.get() == "0": 
                self.var_nregions.set("10")
        else:
            self.entry_nregions.config(state=tk.DISABLED)

    def on_bw_change(self, *args):
        name = self.var_nml_name.get()
        if "_BW" in name and name.endswith(".nml"):
            parts = name.split("_BW")
            bw_str = self.var_bw.get()
            if bw_str.isdigit():
                self.var_nml_name.set(f"{parts[0]}_BW{bw_str}.nml")

    def update_h5_data(self):
        if self.state.h5_path:
            self.var_work_dir.set(os.path.dirname(self.state.h5_path))

        if self.state.pat_w > 0:
            binning = 904 // self.state.pat_w
            self.lbl_binning.config(text=f"{binning}", foreground="black")
            
        if self.state.nx > 0 and self.state.ny > 0:
            self.lbl_roi_max.config(text=f"Max Bounds: Nx={self.state.nx}, Ny={self.state.ny}")
        
        if self.state.acc_voltage:
            self.var_kv.set(str(int(self.state.acc_voltage)))
            
        if self.state.up1_path and self.state.scan_name:
            up1_basename = os.path.splitext(os.path.basename(self.state.up1_path))[0]
            scan_leaf = self.state.scan_name.split('/')[-1].replace(' ', '_')
            bw = self.var_bw.get()
            self.var_nml_name.set(f"{up1_basename}_{scan_leaf}_BW{bw}.nml")

    def reset_defaults(self):
        try:
            with open(utils.DEFAULTS_FILE, 'r') as f:
                defs = json.load(f)
            edax_defs = defs.get("EDAX", {})
            self.var_delta.set(str(edax_defs.get("native_delta", 23.0)))
            self.var_bw.set(str(edax_defs.get("bw", 123)))
            self.var_gausbckg.set(edax_defs.get("gausbckg", True))
            self.var_nregions.set(str(edax_defs.get("nregions", 10)))
            self.var_nthread.set(str(edax_defs.get("nthread", 0)))
            self.var_batchsize.set(str(edax_defs.get("batchsize", 0)))
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load defaults:\n{e}")

    def load_structures(self):
        element = self.var_element.get().strip()
        if not element:
            messagebox.showwarning("Warning", "Please enter an Element.")
            return
        self.combo_struct.set("Loading...")
        self.update_idletasks()
        
        def _fetch():
            try:
                tree_url = "https://api.github.com/repos/EMsoft-org/SHTdatabase/git/trees/master?recursive=1"
                req = urllib.request.Request(tree_url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req) as response:
                    tree_data = json.loads(response.read().decode('utf-8'))
                structures = set()
                for item in tree_data.get('tree', []):
                    path = item['path']
                    if path.endswith('.sht'):
                        basename = os.path.basename(path)
                        parts = basename.split(' ')
                        if parts[0].lower() == element.lower():
                            m = re.search(r'\[(.*?)\]', basename)
                            if m:
                                structures.add(f"[{m.group(1)}]")
                
                def _update():
                    if structures:
                        vals = sorted(list(structures))
                        self.combo_struct['values'] = vals
                        self.combo_struct.set(vals[0])
                    else:
                        self.combo_struct.set("")
                        self.combo_struct['values'] = []
                        messagebox.showinfo("Info", f"No structures found for {element}.")
                self.app.root.after(0, _update)
            except Exception as e:
                self.app.root.after(0, lambda: messagebox.showerror("Error", f"Failed to fetch structures:\n{e}"))
                self.app.root.after(0, lambda: self.combo_struct.set(""))
                
        threading.Thread(target=_fetch, daemon=True).start()

    def fetch_sht(self):
        element = self.var_element.get().strip().lower()
        struct_type = self.var_struct.get().strip().lower()
        if struct_type and not struct_type.startswith('['):
            struct_type = f"[{struct_type}"
        if struct_type and not struct_type.endswith(']'):
            struct_type = f"{struct_type}]"
            
        kv = self.var_kv.get().strip()
        
        if not element or not struct_type or not kv:
            messagebox.showwarning("Missing Data", "Please fill in Element, Structure, and kV.")
            return
            
        tokens = [element, struct_type, f"{{{kv}kv}}".lower()]
        local_dir = os.path.join(utils.SCRIPT_DIR, self.app.config.get("sht_library_dir", "SHT_Library"))
        os.makedirs(local_dir, exist_ok=True)
        
        for local_file in os.listdir(local_dir):
            if local_file.endswith('.sht'):
                parts = local_file.split(' ')
                if parts[0].lower() == element and struct_type in local_file.lower() and f"{{{kv}kv}}".lower() in local_file.lower():
                    local_path = os.path.join(local_dir, local_file)
                    clean_name = utils.sanitize_sht_filename(local_file)
                    clean_path = os.path.join(local_dir, clean_name)
                    if local_path != clean_path:
                        os.rename(local_path, clean_path)
                    self._append_sht_path(clean_path)
                    self.lbl_sht_status.config(text=f"Found Locally: {clean_name}", foreground="green")
                    return
            
        self.lbl_sht_status.config(text="Searching EMsoft GitHub Repository...", foreground="blue")
        self.update_idletasks()
        
        tree_url = "https://api.github.com/repos/EMsoft-org/SHTdatabase/git/trees/master?recursive=1"
        req = urllib.request.Request(tree_url, headers={'User-Agent': 'Mozilla/5.0'})
        try:
            with urllib.request.urlopen(req) as response:
                tree_data = json.loads(response.read().decode('utf-8'))
                
            file_url = None
            found_name = ""
            for item in tree_data.get('tree', []):
                path = item['path']
                if path.endswith('.sht'):
                    basename = os.path.basename(path)
                    parts = basename.split(' ')
                    if parts[0].lower() == element and struct_type in basename.lower() and f"{{{kv}kv}}".lower() in basename.lower():
                        safe_path = urllib.parse.quote(path)
                        file_url = f"https://raw.githubusercontent.com/EMsoft-org/SHTdatabase/master/{safe_path}"
                        found_name = os.path.basename(path)
                        break
            
            if file_url:
                clean_name = utils.sanitize_sht_filename(found_name)
                local_path = os.path.join(local_dir, clean_name)
                self.lbl_sht_status.config(text=f"Downloading {found_name}...", foreground="blue")
                self.update_idletasks()
                
                req_file = urllib.request.Request(file_url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req_file) as response, open(local_path, 'wb') as out_file:
                    out_file.write(response.read())
                    
                self._append_sht_path(local_path)
                self.lbl_sht_status.config(text=f"Downloaded: {clean_name}", foreground="green")
            else:
                self.lbl_sht_status.config(text="Download Failed: No matching file found.", foreground="red")
                messagebox.showerror("Search Error", f"Could not find a .sht file containing {tokens} in EMsoft GitHub.")
        except Exception as e:
            self.lbl_sht_status.config(text="API Connection Failed.", foreground="red")
            messagebox.showerror("Connection Error", f"Failed to connect to GitHub API:\n{e}")

    def browse_sht(self):
        start_dir = os.path.join(utils.SCRIPT_DIR, self.app.config.get("sht_library_dir", "SHT_Library"))
        os.makedirs(start_dir, exist_ok=True)
        filepaths = filedialog.askopenfilenames(initialdir=start_dir, filetypes=[("EMsoft Master Pattern", "*.sht")])
        if filepaths:
            for path in filepaths:
                clean_name = utils.sanitize_sht_filename(os.path.basename(path))
                target_path = os.path.join(start_dir, clean_name)
                if os.path.abspath(path) != os.path.abspath(target_path):
                    shutil.copy2(path, target_path)
                self._append_sht_path(target_path)
            self.lbl_sht_status.config(text=f"Total: {self.sht_listbox.size()} file(s) in list", foreground="green")

    def generate_and_queue(self):
        if not self.state.up1_path or not self.state.h5_path:
            messagebox.showerror("Error", "Please load UP1 and H5 files in Tab 1 first.")
            return
            
        sht_paths = list(self.sht_listbox.get(0, tk.END))
        if not sht_paths:
            messagebox.showerror("Error", "Please fetch or specify at least one valid Master Pattern (.sht) file first.")
            return
            
        for p in sht_paths:
            if not os.path.exists(p):
                messagebox.showerror("Error", f"Master pattern file not found:\n{p}")
                return
            
        out_nml_name = self.var_nml_name.get()
        if not out_nml_name:
             messagebox.showerror("Error", "Please specify an Output NML File Name.")
             return

        h5_dir = os.path.dirname(self.state.h5_path)
        out_nml = os.path.join(h5_dir, out_nml_name)

        if os.path.exists(out_nml):
            msg = f"The file '{out_nml_name}' already exists.\n\nDo you want to Overwrite it?\n\nYes = Overwrite\nNo = Create new file with appended number\nCancel = Abort"
            choice = messagebox.askyesnocancel("File Exists", msg)
            if choice is None:
                return
            elif choice is False:
                base, ext = os.path.splitext(out_nml)
                base = re.sub(r'_\d+$', '', base)
                counter = 1
                while os.path.exists(f"{base}_{counter}{ext}"):
                    counter += 1
                out_nml = f"{base}_{counter}{ext}"
                out_nml_name = os.path.basename(out_nml)
                self.var_nml_name.set(out_nml_name)

        try:
            bw = int(self.var_bw.get())
            native_delta = float(self.var_delta.get())
            gausbckg = self.var_gausbckg.get()
            nthread = int(self.var_nthread.get())
            batchsize = int(self.var_batchsize.get())
            
            nregions = int(self.var_nregions.get()) if gausbckg else 0
            
            if "EDAX" not in self.app.params: self.app.params["EDAX"] = {}
            self.app.params["EDAX"]["bw"] = bw
            self.app.params["EDAX"]["nregions"] = int(self.var_nregions.get()) 
            self.app.params["EDAX"]["native_delta"] = native_delta
            self.app.params["EDAX"]["gausbckg"] = gausbckg
            self.app.params["EDAX"]["nthread"] = nthread
            self.app.params["EDAX"]["batchsize"] = batchsize
            utils.save_json(utils.PARAMS_FILE, self.app.params)
            
            if self.var_use_roi.get():
                rx = int(self.var_roi_x0.get())
                ry = int(self.var_roi_y0.get())
                rw = int(self.var_roi_w.get())
                rh = int(self.var_roi_h.get())
                
                if rx < 0 or ry < 0 or rx + rw > self.state.nx or ry + rh > self.state.ny:
                    messagebox.showerror("ROI Bounds Error", f"ROI boundaries exceed the maximum map dimensions (Nx={self.state.nx}, Ny={self.state.ny}).")
                    return
                roi_str = f"'{rx}, {ry}, {rw}, {rh}'"
            else:
                roi_str = "''"
                
        except ValueError:
            messagebox.showerror("Error", "Invalid parameter formats. Ensure numbers are valid.")
            return

        binning = 904 // self.state.pat_w
        delta = native_delta * binning
        
        pcx, pcy, pcz = self.state.pc
        PCx_emsoft = self.state.pat_w * (pcx - 0.5)
        PCy_emsoft = self.state.pat_w * pcy - 0.5 * self.state.pat_h
        DD_emsoft  = self.state.pat_w * pcz * delta

        write_up1 = utils.to_execution_path(self.state.up1_path, self.app.config)
        master_paths = [utils.to_execution_path(p, self.app.config) for p in sht_paths]
        masterfile_str = ",".join(utils.nml_string(p) for p in master_paths) + ","
        write_out = utils.to_execution_path(out_nml, self.app.config)

        try:
            with open(out_nml, "w", newline='\n') as f:
                f.write(" &EMSphInx\n")
                f.write("!#################################################################\n")
                f.write("! Input Files\n")
                f.write("!#################################################################\n")
                f.write(f" patfile    = {utils.nml_string(write_up1)},\n\n")
                f.write(f" masterfile = {masterfile_str}\n\n")
                f.write("!#################################################################\n")
                f.write("! Pattern Processing\n")
                f.write("!#################################################################\n")
                f.write(f" patdims    = {self.state.pat_w}, {self.state.pat_h},\n")
                
                circmask_val = self.var_circmask.get().split()[0]
                f.write(f" circmask   = {circmask_val},\n")
                
                gaus_str = ".TRUE." if gausbckg else ".FALSE."
                f.write(f" gausbckg   = {gaus_str},\n")
                f.write(f" nregions   = {nregions},\n\n")
                f.write("!#################################################################\n")
                f.write("! Camera Calibration\n")
                f.write("!#################################################################\n")
                f.write(f" delta      = {delta},\n")
                f.write(f" pctr       = {PCx_emsoft:.6f}, {PCy_emsoft:.6f}, {DD_emsoft:.6f},\n")
                f.write(" vendor     = 'EMsoft',\n")
                f.write(" thetac     = 0.0,\n\n")
                f.write("!#################################################################\n")
                f.write("! Scan Information\n")
                f.write("!#################################################################\n")
                f.write(f" scandims   = {self.state.nx}, {self.state.ny}, {self.state.step_size},\n")
                f.write(f" roimask    = {roi_str},\n\n")
                f.write("!#################################################################\n")
                f.write("! Indexing Parameters\n")
                f.write("!#################################################################\n")
                f.write(f" bw         = {bw},\n")
                f.write(" normed     = .FALSE.,\n")
                f.write(" refine     = .TRUE.,\n")
                f.write(f" nthread    = {nthread},\n")
                f.write(f" batchsize  = {batchsize},\n\n")
                f.write("!#################################################################\n")
                f.write("! Output Files\n")
                f.write("!#################################################################\n")
                base_out = os.path.splitext(write_out)[0]
                f.write(f" datafile   = {utils.nml_string(base_out + '.h5')},\n")
                f.write(f" vendorfile = {utils.nml_string(base_out + '.ang')},\n")
                f.write(f" ipfmap     = {utils.nml_string(base_out + '_ipf.png')},\n")
                f.write(f" qualmap    = {utils.nml_string(base_out + '_q.png')}\n")
                f.write(" /\n")

            self.app.tab_queue.add_job(self.state.scan_name, out_nml)
            self.app.notebook.select(self.app.tab_queue)
            self.app.tab_queue.start_queue()
        except Exception as e:
            messagebox.showerror("NML Error", f"Failed to write NML file:\n{e}")
