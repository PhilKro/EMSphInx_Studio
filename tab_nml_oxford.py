import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
os.environ["HDF5_USE_FILE_LOCKING"] = "FALSE" # Fixes "Link iteration failed / eoa=2048" on Windows network drives
import h5py
import hdf5plugin
import os
import struct
import numpy as np
import threading
import time
import re
import urllib.request
import urllib.parse
import json
import shutil
from PIL import Image, ImageTk
import utils
import webbrowser
from oxford_filenames import next_nml_name, output_name_parts
from oxford_metadata import (
    beam_voltage_lookup_labels,
    format_beam_voltage_kv,
    format_step_size_um,
)

try:
    import matplotlib.cm as cm
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

class TabNMLOxford(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.state = app.shared_state
        self._is_updating_ui = False
        self._setup_ui()

    def _setup_ui(self):
        ttk.Label(self, text="Oxford: EMsoft NML Generator", font=("Helvetica", 14, "bold")).pack(pady=(20, 10))
        
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
        self.var_kv = tk.StringVar(value="20")
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
        self.lbl_binning = ttk.Label(params_frame, text="1 (Calculated from pat dims)", foreground="gray")
        self.lbl_binning.grid(row=0, column=1, sticky=tk.W, padx=10)

        ttk.Label(params_frame, text="Delta (Calculated):").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.var_delta = tk.StringVar(value="Unknown")
        ttk.Entry(params_frame, textvariable=self.var_delta, width=10, state="readonly").grid(row=1, column=1, sticky=tk.W, padx=10)

        ttk.Label(params_frame, text="Bandwidth:").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.var_bw = tk.StringVar(value=str(self.app.params.get("OXFORD", {}).get("bw", 123)))
        self.var_bw.trace_add("write", self.on_bw_change)
        ttk.Entry(params_frame, textvariable=self.var_bw, width=10).grid(row=2, column=1, sticky=tk.W, padx=10)
        
        bw_hint = "Recommended: 53, 63, 68, 74, 88, 95, 113, 122, 123, 158, 172, 188, 203, 221, 263, 284, 313"
        ttk.Label(params_frame, text=bw_hint, foreground="gray", font=("Helvetica", 8)).grid(row=2, column=2, sticky=tk.W, padx=10)

        ttk.Label(params_frame, text="Circular Mask (circmask):").grid(row=3, column=0, sticky=tk.W, pady=5)
        self.var_circmask = tk.StringVar(value="-1 (Disabled)")
        self.combo_circmask = ttk.Combobox(params_frame, textvariable=self.var_circmask, values=["0 (Enabled)", "-1 (Disabled)"], state="readonly", width=15)
        self.combo_circmask.grid(row=3, column=1, sticky=tk.W, padx=10)

        self.var_gausbckg = tk.BooleanVar(value=self.app.params.get("OXFORD", {}).get("gausbckg", False))
        self.var_gausbckg.trace_add("write", self.on_gaus_change)
        ttk.Checkbutton(params_frame, text="Apply Gaussian Background (gausbckg)", variable=self.var_gausbckg).grid(row=4, column=0, columnspan=2, sticky=tk.W, pady=(10, 5))
        
        ttk.Label(params_frame, text="NRegions:").grid(row=5, column=0, sticky=tk.W, pady=5)
        self.var_nregions = tk.StringVar(value=str(self.app.params.get("OXFORD", {}).get("nregions", 0)))
        self.entry_nregions = ttk.Entry(params_frame, textvariable=self.var_nregions, width=10)
        self.entry_nregions.grid(row=5, column=1, sticky=tk.W, padx=10)
        self.on_gaus_change()

        ttk.Label(params_frame, text="Threads (nthread):").grid(row=6, column=0, sticky=tk.W, pady=5)
        self.var_nthread = tk.StringVar(value=str(self.app.params.get("OXFORD", {}).get("nthread", 0)))
        ttk.Entry(params_frame, textvariable=self.var_nthread, width=10).grid(row=6, column=1, sticky=tk.W, padx=10)

        ttk.Label(params_frame, text="Batch Size (batchsize):").grid(row=7, column=0, sticky=tk.W, pady=5)
        self.var_batchsize = tk.StringVar(value=str(self.app.params.get("OXFORD", {}).get("batchsize", 0)))
        ttk.Entry(params_frame, textvariable=self.var_batchsize, width=10).grid(row=7, column=1, sticky=tk.W, padx=10)
        
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

        # 4. Output Names
        output_frame = ttk.LabelFrame(content, text="Output Paths", padding=10)
        output_frame.pack(fill=tk.X, pady=10)
        
        ttk.Label(output_frame, text="Output UP1 Name:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.var_up1_name = tk.StringVar()
        ttk.Entry(output_frame, textvariable=self.var_up1_name, width=60).grid(row=0, column=1, sticky=tk.W, padx=10)
        
        ttk.Label(output_frame, text="Output NML Name:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.var_nml_name = tk.StringVar()
        ttk.Entry(output_frame, textvariable=self.var_nml_name, width=60).grid(row=1, column=1, sticky=tk.W, padx=10)

        # Progress
        self.lbl_progress = ttk.Label(content, text="")
        self.lbl_progress.pack(fill=tk.X, pady=5)

        # Action Buttons
        btn_frame = ttk.Frame(content)
        btn_frame.pack(fill=tk.X, pady=20)
        
        self.btn_queue = ttk.Button(btn_frame, text="Create NML and up1 & add to job queue", command=self.generate_and_queue)
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
            if hasattr(self.app, 'tab_viewer_oxford'):
                self.app.tab_viewer_oxford.draw_roi_from_state()
            return
        try:
            rx = int(self.var_roi_x0.get() or 0)
            ry = int(self.var_roi_y0.get() or 0)
            rw = int(self.var_roi_w.get() or 0)
            rh = int(self.var_roi_h.get() or 0)
            self.state.roi = (rx, ry, rw, rh)
            self.state.use_roi = True
            if hasattr(self.app, 'tab_viewer_oxford'):
                self.app.tab_viewer_oxford.draw_roi_from_state()
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
            binning = 1
            if hasattr(self.app.tab_viewer_oxford, 'h5_file') and self.app.tab_viewer_oxford.h5_file is not None:
                h5_file = self.app.tab_viewer_oxford.h5_file
                if self.state.scan_name in h5_file:
                    hdr = h5_file[self.state.scan_name]["Header"]
                    if "Camera Binning Mode" in hdr:
                        bin_mode = hdr["Camera Binning Mode"][0].decode('utf-8') if isinstance(hdr["Camera Binning Mode"][0], bytes) else str(hdr["Camera Binning Mode"][0])
                        # Oxford binning usually handled inside, EMSphInx can use native_delta * binning.
                        # Wait, we might not need to parse binning, just use 1.
            self.lbl_binning.config(text="1 (Directly from H5)", foreground="black")
            
        if hasattr(self.state, 'native_delta'):
            self.var_delta.set(str(self.state.native_delta))
            
        if self.state.nx > 0 and self.state.ny > 0:
            self.lbl_roi_max.config(text=f"Max Bounds: Nx={self.state.nx}, Ny={self.state.ny}")
        
        if self.state.acc_voltage:
            self.var_kv.set(format_beam_voltage_kv(self.state.acc_voltage))
            
        if self.state.h5_path and self.state.scan_name:
            map_name = getattr(self.state, 'map_name', 'Map')
            bw = self.var_bw.get()
            h5_dir = os.path.dirname(self.state.h5_path)
            up1_name, _legacy_up1, nml_prefix, legacy_nml_prefix = output_name_parts(
                self.state.h5_path, map_name, bw
            )

            # New files omit the H5 map label. Legacy NML names still reserve the
            # corresponding sequence number so an old job is never overlooked.
            self.var_up1_name.set(up1_name)
            self.var_nml_name.set(
                next_nml_name(h5_dir, nml_prefix, legacy_nml_prefix)
            )

    def reset_defaults(self):
        try:
            with open(utils.DEFAULTS_FILE, 'r') as f:
                defs = json.load(f)
            ox_defs = defs.get("OXFORD", {})
            self.var_bw.set(str(ox_defs.get("bw", 123)))
            self.var_gausbckg.set(ox_defs.get("gausbckg", False))
            self.var_nregions.set(str(ox_defs.get("nregions", 0)))
            self.var_nthread.set(str(ox_defs.get("nthread", 0)))
            self.var_batchsize.set(str(ox_defs.get("batchsize", 0)))
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
            
        try:
            kv_labels = beam_voltage_lookup_labels(kv)
        except ValueError:
            messagebox.showwarning("Invalid Data", "Beam voltage must be numeric.")
            return

        kv_tokens = tuple(f"{{{label}kv}}".lower() for label in kv_labels)
        tokens = [element, struct_type, " or ".join(kv_tokens)]
        local_dir = os.path.join(utils.SCRIPT_DIR, self.app.config.get("sht_library_dir", "SHT_Library"))
        os.makedirs(local_dir, exist_ok=True)
        
        for local_file in os.listdir(local_dir):
            if local_file.endswith('.sht'):
                parts = local_file.split(' ')
                if parts[0].lower() == element and struct_type in local_file.lower() and any(token in local_file.lower() for token in kv_tokens):
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
                    if parts[0].lower() == element and struct_type in basename.lower() and any(token in basename.lower() for token in kv_tokens):
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
        if not self.state.h5_path:
            messagebox.showerror("Error", "Please load an H5OINA file in Tab 1 first.")
            return
            
        sht_paths = list(self.sht_listbox.get(0, tk.END))
        if not sht_paths:
            messagebox.showerror("Error", "Please fetch or specify at least one valid Master Pattern (.sht) file first.")
            return
            
        out_nml_name = self.var_nml_name.get()
        out_up1_name = self.var_up1_name.get()
        if not out_nml_name or not out_up1_name:
             messagebox.showerror("Error", "Please specify both Output UP1 and NML File Names.")
             return

        h5_dir = os.path.dirname(self.state.h5_path)
        out_nml = os.path.join(h5_dir, out_nml_name)
        out_up1 = os.path.join(h5_dir, out_up1_name)

        skip_up1 = False
        existing_up1 = out_up1 if os.path.exists(out_up1) else None
        map_name = getattr(self.state, 'map_name', 'Map')
        clean_up1_name, legacy_up1_name, _clean_nml, _legacy_nml = output_name_parts(
            self.state.h5_path, map_name, self.var_bw.get()
        )
        if not existing_up1 and out_up1_name == clean_up1_name:
            legacy_up1 = os.path.join(h5_dir, legacy_up1_name)
            if legacy_up1 != out_up1 and os.path.exists(legacy_up1):
                existing_up1 = legacy_up1

        if existing_up1:
            msg = f"The UP1 file already exists:\n{existing_up1}\n\nDo you want to use the existing file (Yes) or generate a new one (No)?"
            ans = messagebox.askyesnocancel("UP1 Exists", msg)
            if ans is None:
                return # Cancelled
            elif ans:
                skip_up1 = True # Yes, use existing
                out_up1 = existing_up1
            else:
                skip_up1 = False # No, generate using the new clean name

        if os.path.exists(out_nml):
            msg = f"The NML file already exists.\n\nDo you want to overwrite it?"
            if not messagebox.askyesno("File Exists", msg):
                return

        try:
            bw = int(self.var_bw.get())
            native_delta = float(self.var_delta.get())
            gausbckg = self.var_gausbckg.get()
            nthread = int(self.var_nthread.get())
            batchsize = int(self.var_batchsize.get())
            
            nregions = int(self.var_nregions.get()) if gausbckg else 0
            
            if "OXFORD" not in self.app.params: self.app.params["OXFORD"] = {}
            self.app.params["OXFORD"]["bw"] = bw
            self.app.params["OXFORD"]["nregions"] = nregions
            self.app.params["OXFORD"]["gausbckg"] = gausbckg
            self.app.params["OXFORD"]["nthread"] = nthread
            self.app.params["OXFORD"]["batchsize"] = batchsize
            utils.save_json(utils.PARAMS_FILE, self.app.params)
        except ValueError:
            messagebox.showerror("Error", "Invalid parameter formats.")
            return

        pat_type = "Processed Patterns"
        if hasattr(self.app.tab_viewer_oxford, 'combo_pat_type'):
            pat_type = self.app.tab_viewer_oxford.var_pat_type.get()

        # Calculate memory requirements for the UP1 chunk (10GB max or file size)
        import h5py
        req_mem = 0
        if not skip_up1:
            try:
                with h5py.File(self.state.h5_path, 'r', swmr=True, libver='latest') as f:
                    d_shape = f[self.state.scan_name]["Data"][pat_type].shape
                    bytes_per_pattern = d_shape[1] * d_shape[2]
                    total_bytes = d_shape[0] * bytes_per_pattern
                    req_mem = min(10 * 1024 * 1024 * 1024, total_bytes)
            except Exception:
                req_mem = 10 * 1024 * 1024 * 1024 # default fallback
        
        active_mem = sum(t["mem"] for t in self.app.shared_state.up1_tasks.values())
        avail_mem = utils.get_available_memory()
        
        if req_mem + active_mem > avail_mem - (2 * 1024 * 1024 * 1024): # 2GB safety
            msg = f"Warning: High memory usage detected.\nRequired: {(req_mem + active_mem) / 1e9:.1f} GB\nAvailable: {avail_mem / 1e9:.1f} GB\nProceed anyway?"
            if not messagebox.askyesno("Memory Warning", msg):
                return

        # Prepare job config
        roi_str = "''"
        if self.var_use_roi.get():
            rx, ry = int(self.var_roi_x0.get()), int(self.var_roi_y0.get())
            rw, rh = int(self.var_roi_w.get()), int(self.var_roi_h.get())
            roi_str = f"'{rx}, {ry}, {rw}, {rh}'"
            
        # Generate NML file synchronously before adding to queue
        pcx, pcy, dd = self.state.pc
        PC_X_Emsoft = self.state.pat_w * (pcx - 0.5)
        PC_Y_Emsoft = self.state.pat_w * pcy - 0.5 * self.state.pat_h
        DD_Emsoft = self.state.pat_w * dd * native_delta

        write_up1 = utils.to_execution_path(out_up1, self.app.config)
        master_paths = [utils.to_execution_path(p, self.app.config) for p in sht_paths]
        masterfile_str = ",".join(utils.nml_string(p) for p in master_paths) + ","
        write_out = utils.to_execution_path(out_nml, self.app.config)
        base_out = os.path.splitext(write_out)[0]

        try:
            with open(out_nml, "w", newline='\n') as f_nml:
                f_nml.write(" &EMSphInx\n")
                f_nml.write("!#################################################################\n")
                f_nml.write("! Input Files\n")
                f_nml.write("!#################################################################\n")
                f_nml.write(f" patfile    = {utils.nml_string(write_up1)},\n\n")
                f_nml.write(f" masterfile = {masterfile_str}\n\n")
                f_nml.write("!#################################################################\n")
                f_nml.write("! Pattern Processing\n")
                f_nml.write("!#################################################################\n")
                f_nml.write(f" patdims    = {self.state.pat_w}, {self.state.pat_h},\n")
                
                circmask_val = self.var_circmask.get().split()[0]
                f_nml.write(f" circmask   = {circmask_val},\n")
                
                gaus_str = ".TRUE." if gausbckg else ".FALSE."
                f_nml.write(f" gausbckg   = {gaus_str},\n")
                f_nml.write(f" nregions   = {nregions},\n\n")
                f_nml.write("!#################################################################\n")
                f_nml.write("! Camera Calibration\n")
                f_nml.write("!#################################################################\n")
                f_nml.write(f" delta      = {native_delta},\n")
                f_nml.write(f" pctr       = {PC_X_Emsoft:.6f}, {PC_Y_Emsoft:.6f}, {DD_Emsoft:.6f},\n")
                f_nml.write(" vendor     = 'EMsoft',\n")
                f_nml.write(" thetac     = 0.0,\n\n")
                f_nml.write("!#################################################################\n")
                f_nml.write("! Scan Information\n")
                f_nml.write("!#################################################################\n")
                step_size = format_step_size_um(self.state.step_size)
                f_nml.write(f" scandims   = {self.state.nx}, {self.state.ny}, {step_size},\n")
                f_nml.write(f" roimask    = {roi_str},\n\n")
                f_nml.write("!#################################################################\n")
                f_nml.write("! Indexing Parameters\n")
                f_nml.write("!#################################################################\n")
                f_nml.write(f" bw         = {bw},\n")
                f_nml.write(" normed     = .FALSE.,\n")
                f_nml.write(" refine     = .TRUE.,\n")
                f_nml.write(f" nthread    = {nthread},\n")
                f_nml.write(f" batchsize  = {batchsize},\n\n")
                f_nml.write("!#################################################################\n")
                f_nml.write("! Output Files\n")
                f_nml.write("!#################################################################\n")
                f_nml.write(f" datafile   = {utils.nml_string(base_out + '.h5')},\n")
                f_nml.write(f" vendorfile = {utils.nml_string(base_out + '.ang')},\n")
                f_nml.write(f" ipfmap     = {utils.nml_string(base_out + '_ipf.png')},\n")
                f_nml.write(f" qualmap    = {utils.nml_string(base_out + '_q.png')}\n")
                f_nml.write(" /\n")
        except Exception as e:
            messagebox.showerror("NML Error", f"Failed to write NML file:\n{e}")
            return

        # Prepare job config
        job_config = {
            "out_nml": out_nml, "sht_paths": sht_paths, "bw": bw, "native_delta": native_delta,
            "gausbckg": gausbckg, "nregions": nregions, "nthread": nthread,
            "pc": self.state.pc, "nx": self.state.nx, "ny": self.state.ny, "step_size": self.state.step_size,
            "roi_str": roi_str, "pat_type": pat_type, "skip_up1": skip_up1
        }
        
        # Enqueue immediately
        status_text = "Pending" if skip_up1 else "Writing .up1 file (0.0%)"
        item_id = self.app.tab_queue.add_job(self.state.scan_name, out_nml, status=status_text)
        job_config["item_id"] = item_id

        self.lbl_progress.config(text="Job queued successfully.")
        self.app.notebook.select(self.app.tab_queue)
        self.app.tab_queue.start_queue()
        
        if out_up1 in self.app.shared_state.up1_tasks:
            self.app.shared_state.up1_tasks[out_up1]["jobs"].append(job_config)
        elif not skip_up1:
            self.app.shared_state.up1_tasks[out_up1] = {"mem": req_mem, "jobs": [job_config]}
            threading.Thread(target=self._worker_generate_up1, args=(out_up1, self.state.h5_path, self.state.scan_name), daemon=True).start()

    def _worker_generate_up1(self, out_up1, h5_path, scan_name):
        try:
            task_info = self.app.shared_state.up1_tasks.get(out_up1, {})
            jobs = task_info.get("jobs", [])
            
            if not jobs:
                return # Should not happen

            # We assume the first job defines the pat_type and skip_up1
            pat_type = jobs[0]["pat_type"]
            skip_up1 = jobs[0]["skip_up1"]

            with h5py.File(h5_path, 'r', swmr=True, libver='latest') as f:
                d = f[scan_name]["Data"][pat_type]
                n_patterns, pattern_height, pattern_width = d.shape
                
                if not skip_up1:
                    byte_start = 16
                    up1_version = 1
                    header = np.array([up1_version, pattern_width, pattern_height, byte_start], dtype="<u4")
                    
                    bytes_per_pattern = pattern_height * pattern_width
                    chunk_size = max(1, (10 * 1024 * 1024) // bytes_per_pattern)  # Reduced to 10MB to yield GIL
                    
                    with open(out_up1, "wb") as fid:
                        header.tofile(fid)
                        for start_idx in range(0, n_patterns, chunk_size):
                            if self.app.tab_queue.stop_flag:
                                break
                            
                            end_idx = min(start_idx + chunk_size, n_patterns)
                            patterns = d[start_idx:end_idx]
                            patterns = np.ascontiguousarray(patterns, dtype=np.uint8)
                            patterns.tofile(fid)
                            
                            pct = (end_idx / n_patterns) * 100
                            self.app.root.after(0, self.lbl_progress.config, {"text": f"Writing UP1... {end_idx}/{n_patterns} patterns ({pct:.1f}%)"})
                            for job in jobs:
                                self.app.root.after(0, self.app.tab_queue.safe_tree_update, job["item_id"], "status", f"Writing .up1 file ({pct:.1f}%)")
                            
                            time.sleep(0.01) # Yield to main GUI thread and other disk I/O
                            
                    if self.app.tab_queue.stop_flag:
                        try:
                            os.remove(out_up1)
                        except Exception:
                            pass
                        
                        self.app.root.after(0, self.lbl_progress.config, {"text": "UP1 generation aborted by user."})
                        for job in jobs:
                            self.app.root.after(0, self.app.tab_queue.safe_tree_update, job["item_id"], "status", "Stopped")
                        
                        if out_up1 in self.app.shared_state.up1_tasks:
                            del self.app.shared_state.up1_tasks[out_up1]
                        return
                else:
                    self.app.root.after(0, self.lbl_progress.config, {"text": "Skipped UP1 generation."})
            
            # Set all jobs to Pending so queue can run them
            for job in jobs:
                self.app.root.after(0, self.app.tab_queue.safe_tree_update, job["item_id"], "status", "Pending")

            # Clean up
            if out_up1 in self.app.shared_state.up1_tasks:
                del self.app.shared_state.up1_tasks[out_up1]

            self.app.root.after(0, self.lbl_progress.config, {"text": "Done! Jobs are now Pending."})

        except Exception as e:
            self.app.root.after(0, messagebox.showerror, "Generation Error", f"Failed to generate UP1/NML:\n{e}")
            self.app.root.after(0, self.lbl_progress.config, {"text": "Error occurred."})
