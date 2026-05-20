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

try:
    import matplotlib.cm as cm
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

class TabViewerOxford(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.state = app.shared_state
        
        self.h5_file = None
        self.current_raw_image = None
        self.tk_img_pattern = None
        self.tk_img_map = None
        self.map_data_2d = None 
        self.map_canvas_img_item = None
        self.map_cursor_item = None
        self.roi_canvas_item = None
        self.scans_cache = {}
        
        self.roi_start_x = 0
        self.roi_start_y = 0
        
        self._setup_ui()

    def _setup_ui(self):
        left_panel = ttk.Frame(self, width=380) 
        left_panel.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10), pady=10)
        center_panel = ttk.Frame(self, width=400)
        center_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=10)
        right_panel = ttk.Frame(self, width=400)
        right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5, pady=10)

        # --- LEFT PANEL ---
        lf_files = ttk.LabelFrame(left_panel, text="1. Files & Scan", padding=10)
        lf_files.pack(fill=tk.X, pady=(0, 10))

        self.btn_load_h5 = ttk.Button(lf_files, text="Load .h5oina File", command=self.load_h5oina)
        self.btn_load_h5.pack(fill=tk.X, pady=(0, 5))

        ttk.Label(lf_files, text="Select map from H5:").pack(anchor=tk.W, pady=(5, 2))
        self.combo_scan = ttk.Combobox(lf_files, state="readonly", width=50)
        self.combo_scan.pack(fill=tk.X, pady=(0, 10))
        self.combo_scan.bind("<<ComboboxSelected>>", self.on_scan_select)

        ttk.Label(lf_files, text="Select Patterns:").pack(anchor=tk.W, pady=(5, 2))
        self.var_pat_type = tk.StringVar(value="Processed Patterns")
        self.combo_pat_type = ttk.Combobox(lf_files, textvariable=self.var_pat_type, state="readonly")
        self.combo_pat_type.pack(fill=tk.X, pady=(0, 5))
        self.combo_pat_type.bind("<<ComboboxSelected>>", lambda e: self.update_pattern_image())

        lf_params = ttk.LabelFrame(left_panel, text="2. Grid & Architecture", padding=10)
        lf_params.pack(fill=tk.X, pady=(0, 10))

        grid_frame = ttk.Frame(lf_params)
        grid_frame.pack(fill=tk.X)
        ttk.Label(grid_frame, text="Nx (Cols):").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.var_nx = tk.StringVar(value="0")
        ttk.Entry(grid_frame, textvariable=self.var_nx, width=8, state='readonly').grid(row=0, column=1, padx=2, pady=2)
        ttk.Label(grid_frame, text="Ny (Rows):").grid(row=0, column=2, sticky=tk.W, pady=2)
        self.var_ny = tk.StringVar(value="0")
        ttk.Entry(grid_frame, textvariable=self.var_ny, width=8, state='readonly').grid(row=0, column=3, padx=2, pady=2)

        self.lbl_pat_dims = ttk.Label(lf_params, text="Pattern Dims: Unknown", foreground="blue")
        self.lbl_pat_dims.pack(anchor=tk.W, pady=(10, 0))

        self.var_pat_row_major = tk.BooleanVar(value=True)
        ttk.Checkbutton(lf_params, text="Pattern Pixel Read: Row-Major", variable=self.var_pat_row_major, command=self.refresh_view).pack(anchor=tk.W)
        self.var_map_row_major = tk.BooleanVar(value=True)
        ttk.Checkbutton(lf_params, text="Map Grid Read: Row-Major", variable=self.var_map_row_major, command=self.recalc_map).pack(anchor=tk.W)

        self.btn_init = ttk.Button(lf_params, text="Initialize Interactive Map", command=self.init_viewer)
        self.btn_init.pack(fill=tk.X, pady=(15, 0))

        lf_nav = ttk.LabelFrame(left_panel, text="3. Display Settings", padding=10)
        lf_nav.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(lf_nav, text="Map Field:").pack(anchor=tk.W)
        self.var_map_field = tk.StringVar(value="Band Contrast")
        self.combo_map_field = ttk.Combobox(lf_nav, textvariable=self.var_map_field, state="readonly")
        self.combo_map_field.pack(fill=tk.X, pady=(0, 10))
        self.combo_map_field.bind("<<ComboboxSelected>>", lambda e: self.recalc_map())
        
        ttk.Label(lf_nav, text="Pattern Colormap:").pack(anchor=tk.W)
        self.var_cmap = tk.StringVar(value="Grayscale")
        cmap_options = ["Grayscale"] + (["Plasma", "Magma", "Rainbow"] if MATPLOTLIB_AVAILABLE else [])
        self.combo_cmap = ttk.Combobox(lf_nav, textvariable=self.var_cmap, values=cmap_options, state="readonly")
        self.combo_cmap.pack(fill=tk.X, pady=(0, 15))
        self.combo_cmap.bind("<<ComboboxSelected>>", lambda e: self.update_pattern_image())

        # --- CENTER PANEL ---
        ttk.Label(center_panel, text="Grid Map", font=("Helvetica", 11, "bold")).pack(pady=(0,5))
        ttk.Label(center_panel, text="[Left-Click: Probe | Shift+Drag: Draw ROI]", foreground="gray", font=("Helvetica", 9)).pack(pady=(0,5))
        map_grid = ttk.Frame(center_panel)
        map_grid.pack(expand=True, fill=tk.BOTH)
        
        self.var_x = tk.DoubleVar(value=0)
        self.scale_x = ttk.Scale(map_grid, from_=0, to=1, orient=tk.HORIZONTAL, variable=self.var_x, command=self.on_slide)
        self.scale_x.grid(row=0, column=1, sticky="ew", padx=(0, 10))
        self.scale_x.state(['disabled'])
        
        self.var_y = tk.DoubleVar(value=0)
        self.scale_y = ttk.Scale(map_grid, from_=0, to=1, orient=tk.VERTICAL, variable=self.var_y, command=self.on_slide)
        self.scale_y.grid(row=1, column=0, sticky="ns", pady=(0, 10))
        self.scale_y.state(['disabled'])
        
        self.map_canvas = tk.Canvas(map_grid, bg="black", width=350, height=350, highlightthickness=1, highlightbackground="gray")
        self.map_canvas.grid(row=1, column=1, sticky="nsew")
        
        self.map_canvas.bind("<Button-1>", self.on_map_click)
        self.map_canvas.bind("<B1-Motion>", self.on_map_drag)
        self.map_canvas.bind("<Shift-ButtonPress-1>", self.on_roi_press)
        self.map_canvas.bind("<Shift-B1-Motion>", self.on_roi_drag)
        self.map_canvas.bind("<Shift-ButtonRelease-1>", self.on_roi_release)
        
        map_grid.rowconfigure(1, weight=1)
        map_grid.columnconfigure(1, weight=1)
        
        self.lbl_pos = ttk.Label(center_panel, text="X: 0   |   Y: 0   |   Pattern #: 0", font=("Helvetica", 10, "bold"))
        self.lbl_pos.pack(pady=10)

        # --- RIGHT PANEL ---
        ttk.Label(right_panel, text="Pattern View", font=("Helvetica", 11, "bold")).pack(pady=(0,5))
        self.pat_canvas = tk.Canvas(right_panel, bg="black", highlightthickness=0)
        self.pat_canvas.pack(fill=tk.BOTH, expand=True)
        self.placeholder_txt = self.pat_canvas.create_text(200, 200, text="Load files and Initialize.", fill="gray", font=("Helvetica", 12))
        self.pat_canvas_img_item = None
        self.pat_canvas.bind("<Configure>", self.on_pat_canvas_resize)

    def load_h5oina(self):
        filepath = filedialog.askopenfilename(filetypes=[("Oxford H5OINA", "*.h5oina *.h5")])
        if not filepath: return
        self.state.h5_path = filepath
        self.scans_cache.clear()
        
        if self.h5_file is not None:
            self.h5_file.close()
            self.h5_file = None
        
        try:
            self.h5_file = h5py.File(filepath, 'r', swmr=True, libver='latest')
            
            for key in self.h5_file.keys():
                if isinstance(self.h5_file[key], h5py.Group) and "EBSD" in self.h5_file[key]:
                    ebsd_grp = self.h5_file[key]["EBSD"]
                    if "Header" in ebsd_grp and "Data" in ebsd_grp:
                        header = ebsd_grp["Header"]
                        data = ebsd_grp["Data"]
                        
                        nx = int(utils.get_h5_scalar(header["X Cells"]))
                        ny = int(utils.get_h5_scalar(header["Y Cells"]))
                        step = float(utils.get_h5_scalar(header["X Step"]))
                        kv = float(utils.get_h5_scalar(header.get("Beam Voltage", 20.0)))
                        
                        pcx = float(np.mean(data["Pattern Center X"][()]))
                        pcy = float(np.mean(data["Pattern Center Y"][()]))
                        dd = float(np.mean(data["Detector Distance"][()]))
                        
                        map_fields = []
                        for ds_name in data.keys():
                            ds = data[ds_name]
                            if ds.ndim == 1 and ds.shape[0] == nx * ny:
                                map_fields.append(ds_name)
                                
                        pat_types = []
                        if "Processed Patterns" in data:
                            pat_types.append("Processed Patterns")
                            pat_h, pat_w = data["Processed Patterns"].shape[1:3]
                        if "Unprocessed Patterns" in data:
                            pat_types.append("Unprocessed Patterns")
                            if not pat_types:
                                pat_h, pat_w = data["Unprocessed Patterns"].shape[1:3]
                                
                        if not pat_types:
                            messagebox.showerror("Error", f"No pattern datasets found in {key}/EBSD/Data")
                            continue

                        map_name = "Map"
                        if "Analysis Label" in header:
                            label_val = header["Analysis Label"][0]
                            map_name = label_val.decode('utf-8') if isinstance(label_val, bytes) else str(label_val)
                            map_name = map_name.replace(' ', '_')
                            
                        # Parse Delta from Camera Binning Mode
                        delta = 23.0
                        if "Camera Binning Mode" in header:
                            bmode = header["Camera Binning Mode"][0]
                            bmode = bmode.decode('utf-8') if isinstance(bmode, bytes) else str(bmode)
                            bmode = bmode.lower()
                            if "speed 2" in bmode:
                                delta = 160.0
                            elif "speed 1" in bmode or "sensitivity" in bmode:
                                delta = 40.0
                            elif "full" in bmode or "resolution" in bmode:
                                delta = 20.0

                        self.scans_cache[f"{key}/EBSD"] = {
                            "nx": nx, "ny": ny, "step": step, "kv": kv, "pc": (pcx, pcy, dd),
                            "map_fields": map_fields, "pat_types": pat_types,
                            "pat_h": pat_h, "pat_w": pat_w, "map_name": map_name, "delta": delta
                        }
            
            scans = sorted(list(self.scans_cache.keys()))
            if scans:
                self.combo_scan['values'] = scans
                self.combo_scan.current(0)
                self.on_scan_select(None)
            else:
                self.combo_scan['values'] = []
                self.combo_scan.set('')
                messagebox.showwarning("No Scans", "Could not find Oxford EBSD maps.")
                
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def on_scan_select(self, event):
        scan = self.combo_scan.get()
        if scan in self.scans_cache:
            data = self.scans_cache[scan]
            self.var_nx.set(str(data["nx"]))
            self.var_ny.set(str(data["ny"]))
            
            self.state.scan_name = scan
            self.state.nx = data["nx"]
            self.state.ny = data["ny"]
            self.state.step_size = data["step"]
            self.state.acc_voltage = data["kv"]
            self.state.pc = data["pc"]
            
            self.state.pat_w = data["pat_w"]
            self.state.pat_h = data["pat_h"]
            self.lbl_pat_dims.config(text=f"Pattern Dims: {self.state.pat_w} x {self.state.pat_h}")
            if "delta" in data:
                self.state.native_delta = data["delta"]
            if "map_name" in data:
                self.state.map_name = data["map_name"]
            
            self.combo_pat_type['values'] = data["pat_types"]
            if "Processed Patterns" in data["pat_types"]:
                self.combo_pat_type.set("Processed Patterns")
            else:
                self.combo_pat_type.current(0)
            
            fields = sorted(data.get("map_fields", []))
            self.combo_map_field['values'] = fields
            if "Band Contrast" in fields:
                self.combo_map_field.set("Band Contrast")
            elif fields:
                self.combo_map_field.current(0)
            
            if hasattr(self.app, 'tab_nml_oxford'):
                self.app.tab_nml_oxford.update_h5_data()

    def init_viewer(self):
        if not self.state.h5_path or self.h5_file is None:
            messagebox.showerror("Error", "Please load a valid .h5oina file first.")
            return

        nx, ny = self.state.nx, self.state.ny
        
        try:
            self.scale_x.config(to=max(1, nx-1))
            self.scale_y.config(to=max(1, ny-1))
            self.var_x.set(0); self.var_y.set(0)
            self.scale_x.state(['!disabled']); self.scale_y.state(['!disabled'])
            self.pat_canvas.delete(self.placeholder_txt)
            self.recalc_map()
        except Exception as e:
            messagebox.showerror("Init Error", str(e))

    def recalc_map(self):
        if not self.state.nx or not self.state.ny or self.h5_file is None: return
        field = self.var_map_field.get()
        if not field: return
        
        try:
            ds = self.h5_file[self.state.scan_name]["Data"][field]
            data_1d = ds[:]
        except Exception as e:
            print(f"Failed to read H5 map data: {e}")
            return

        expected_len = self.state.nx * self.state.ny
        if len(data_1d) != expected_len:
            data_1d = np.resize(data_1d, expected_len)

        if self.var_map_row_major.get():
            self.map_data_2d = data_1d.reshape((self.state.ny, self.state.nx), order='C')
        else:
            self.map_data_2d = data_1d.reshape((self.state.nx, self.state.ny), order='F').T
            
        map_min, map_max = self.map_data_2d.min(), self.map_data_2d.max()
        norm_map = ((self.map_data_2d - map_min) / (map_max - map_min) * 255).astype(np.uint8) if map_max > map_min else self.map_data_2d.astype(np.uint8)
        self.draw_map_image(Image.fromarray(norm_map, mode='L'))
        
        self.update_pattern_image() 
        self.draw_roi_from_state()

    def draw_map_image(self, img_pil):
        self.map_canvas.update_idletasks()
        cw, ch = self.map_canvas.winfo_width(), self.map_canvas.winfo_height()
        if cw < 10: cw, ch = 350, 350
        
        self.map_scale_x, self.map_scale_y = cw / img_pil.width, ch / img_pil.height
        self.tk_img_map = ImageTk.PhotoImage(img_pil.resize((cw, ch), Image.Resampling.NEAREST))
        
        if self.map_canvas_img_item is None:
            self.map_canvas_img_item = self.map_canvas.create_image(0, 0, image=self.tk_img_map, anchor=tk.NW)
        else:
            self.map_canvas.itemconfig(self.map_canvas_img_item, image=self.tk_img_map)

    def refresh_view(self):
        self.update_pattern_image()

    def on_slide(self, event=None):
        self.update_pattern_image()

    def on_map_click(self, event):
        if self.map_data_2d is not None: self.update_xy_from_click(event.x, event.y)

    def on_map_drag(self, event):
        if self.map_data_2d is not None: self.update_xy_from_click(event.x, event.y)

    def update_xy_from_click(self, cx, cy):
        grid_x = max(0, min(self.state.nx - 1, int(cx / self.map_scale_x)))
        grid_y = max(0, min(self.state.ny - 1, int(cy / self.map_scale_y)))
        self.var_x.set(grid_x); self.var_y.set(grid_y)
        self.update_pattern_image()

    def draw_roi_from_state(self):
        if not hasattr(self, 'map_scale_x'): return
        if not self.state.use_roi:
            if self.roi_canvas_item:
                self.map_canvas.delete(self.roi_canvas_item)
                self.roi_canvas_item = None
            return
            
        x0, y0, w, h = self.state.roi
        x0 = max(0, min(self.state.nx - 1, x0))
        y0 = max(0, min(self.state.ny - 1, y0))
        w = max(1, min(self.state.nx - x0, w))
        h = max(1, min(self.state.ny - y0, h))
        
        x1, y1 = x0 * self.map_scale_x, y0 * self.map_scale_y
        x2, y2 = (x0 + w) * self.map_scale_x, (y0 + h) * self.map_scale_y
        
        if self.roi_canvas_item:
            self.map_canvas.coords(self.roi_canvas_item, x1, y1, x2, y2)
        else:
            self.roi_canvas_item = self.map_canvas.create_rectangle(x1, y1, x2, y2, outline='cyan', width=2, dash=(4, 4))

    def on_roi_press(self, event):
        if self.map_data_2d is None: return
        self.roi_start_x = event.x
        self.roi_start_y = event.y
        if self.roi_canvas_item:
            self.map_canvas.delete(self.roi_canvas_item)
        self.roi_canvas_item = self.map_canvas.create_rectangle(self.roi_start_x, self.roi_start_y, event.x, event.y, outline='cyan', width=2, dash=(4, 4))

    def on_roi_drag(self, event):
        if self.roi_canvas_item:
            self.map_canvas.coords(self.roi_canvas_item, self.roi_start_x, self.roi_start_y, event.x, event.y)

    def on_roi_release(self, event):
        if not self.roi_canvas_item: return
        x1, y1 = self.roi_start_x / self.map_scale_x, self.roi_start_y / self.map_scale_y
        x2, y2 = event.x / self.map_scale_x, event.y / self.map_scale_y
        grid_x1, grid_x2 = sorted([x1, x2])
        grid_y1, grid_y2 = sorted([y1, y2])
        gx0 = max(0, int(grid_x1))
        gy0 = max(0, int(grid_y1))
        gw = min(self.state.nx - gx0, int(grid_x2 - grid_x1))
        gh = min(self.state.ny - gy0, int(grid_y2 - grid_y1))

        if gw > 0 and gh > 0:
            self.state.roi = (gx0, gy0, gw, gh)
            self.state.use_roi = True
            if hasattr(self.app, 'tab_nml_oxford'):
                self.app.tab_nml_oxford.update_roi_ui()
            self.lbl_pos.config(text=f"ROI Mapped: X0={gx0}, Y0={gy0}, W={gw}, H={gh}")
        else:
            self.map_canvas.delete(self.roi_canvas_item)
            self.roi_canvas_item = None
            self.state.use_roi = False
            if hasattr(self.app, 'tab_nml_oxford'):
                self.app.tab_nml_oxford.update_roi_ui()

    def get_1d_index(self, x, y):
        if self.var_map_row_major.get():
            return (y * self.state.nx) + x
        else:
            return (x * self.state.ny) + y

    def update_pattern_image(self):
        if self.h5_file is None: return
        x, y = int(round(self.var_x.get())), int(round(self.var_y.get()))
        idx = self.get_1d_index(x, y)
        current_lbl = self.lbl_pos.cget("text")
        if not current_lbl.startswith("ROI Mapped"):
            self.lbl_pos.config(text=f"X: {x}   |   Y: {y}   |   Pattern #: {idx}")
        
        rect_x1, rect_y1 = x * self.map_scale_x, y * self.map_scale_y
        rect_x2, rect_y2 = (x + 1) * self.map_scale_x, (y + 1) * self.map_scale_y
        if self.map_cursor_item is None:
            self.map_cursor_item = self.map_canvas.create_rectangle(rect_x1, rect_y1, rect_x2, rect_y2, outline='red', width=2)
        else:
            self.map_canvas.coords(self.map_cursor_item, rect_x1, rect_y1, rect_x2, rect_y2)

        pat_type = self.var_pat_type.get()
        if not pat_type: return
        
        try:
            ds = self.h5_file[self.state.scan_name]["Data"][pat_type]
            if idx >= ds.shape[0]: return
            raw_2d = ds[idx]
        except Exception as e:
            print(f"Failed to load pattern: {e}")
            return
            
        if not self.var_pat_row_major.get():
            raw_2d = raw_2d.T
            
        if raw_2d.dtype != np.uint8:
            rmin, rmax = raw_2d.min(), raw_2d.max()
            if rmax > rmin:
                raw_2d = ((raw_2d - rmin) / (rmax - rmin) * 255).astype(np.uint8)
            else:
                raw_2d = raw_2d.astype(np.uint8)

        cmap = self.var_cmap.get()
        if cmap in ["Plasma", "Magma", "Rainbow"] and MATPLOTLIB_AVAILABLE:
            colored = getattr(cm, cmap.lower())(raw_2d / 255.0)
            self.current_raw_image = Image.fromarray((colored[:, :, :3] * 255).astype(np.uint8), mode='RGB')
        else:
            self.current_raw_image = Image.fromarray(raw_2d, mode='L')
        self.draw_pat_canvas()

    def draw_pat_canvas(self):
        if self.current_raw_image is None: return
        disp_size = max(350, min(self.pat_canvas.winfo_width(), self.pat_canvas.winfo_height()))
        self.tk_img_pattern = ImageTk.PhotoImage(self.current_raw_image.resize((disp_size, disp_size), Image.Resampling.LANCZOS))
        cx, cy = self.pat_canvas.winfo_width()//2, self.pat_canvas.winfo_height()//2
        if self.pat_canvas_img_item is None:
            self.pat_canvas_img_item = self.pat_canvas.create_image(cx, cy, image=self.tk_img_pattern, anchor=tk.CENTER)
        else:
            self.pat_canvas.itemconfig(self.pat_canvas_img_item, image=self.tk_img_pattern)
            self.pat_canvas.coords(self.pat_canvas_img_item, cx, cy)

    def on_pat_canvas_resize(self, event):
        self.draw_pat_canvas()

class TabNMLOxford(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.state = app.shared_state
        self._is_updating_ui = False
        self._setup_ui()

    def _setup_ui(self):
        ttk.Label(self, text="Oxford: EMsoft NML Generator", font=("Helvetica", 14, "bold")).pack(pady=(20, 10))
        
        content = ttk.Frame(self)
        content.pack(fill=tk.BOTH, expand=True, padx=40)

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
        ttk.Entry(sht_frame, textvariable=self.var_struct, width=8).grid(row=0, column=3, padx=(5, 15))

        ttk.Label(sht_frame, text="kV:").grid(row=0, column=4, sticky=tk.W, pady=5)
        self.var_kv = tk.StringVar(value="20")
        ttk.Entry(sht_frame, textvariable=self.var_kv, width=8).grid(row=0, column=5, padx=(5, 15))

        self.btn_fetch_sht = ttk.Button(sht_frame, text="Find/Fetch SHT from GitHub API", command=self.fetch_sht)
        self.btn_fetch_sht.grid(row=0, column=6, padx=(10, 0))

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
        btn_frame_sht.grid(row=1, column=6, sticky=tk.NW, pady=(10, 5))
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

        ttk.Label(params_frame, text="Native Delta:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.var_delta = tk.StringVar(value=str(self.app.params.get("native_delta", 23.0)))
        ttk.Entry(params_frame, textvariable=self.var_delta, width=10).grid(row=1, column=1, sticky=tk.W, padx=10)

        ttk.Label(params_frame, text="Bandwidth:").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.var_bw = tk.StringVar(value=str(self.app.params.get("bw", 123)))
        self.var_bw.trace_add("write", self.on_bw_change)
        ttk.Entry(params_frame, textvariable=self.var_bw, width=10).grid(row=2, column=1, sticky=tk.W, padx=10)
        
        bw_hint = "Recommended: 53, 63, 68, 74, 88, 95, 113, 122, 123, 158, 172, 188, 203, 221, 263, 284, 313"
        ttk.Label(params_frame, text=bw_hint, foreground="gray", font=("Helvetica", 8)).grid(row=2, column=2, sticky=tk.W, padx=10)

        self.var_gausbckg = tk.BooleanVar(value=False) # default off for Oxford
        self.var_gausbckg.trace_add("write", self.on_gaus_change)
        ttk.Checkbutton(params_frame, text="Apply Gaussian Background (gausbckg)", variable=self.var_gausbckg).grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=(10, 5))
        
        ttk.Label(params_frame, text="NRegions:").grid(row=4, column=0, sticky=tk.W, pady=5)
        self.var_nregions = tk.StringVar(value=str(self.app.params.get("nregions", 4)))
        self.entry_nregions = ttk.Entry(params_frame, textvariable=self.var_nregions, width=10)
        self.entry_nregions.grid(row=4, column=1, sticky=tk.W, padx=10)
        self.on_gaus_change()

        ttk.Label(params_frame, text="Threads (nthread):").grid(row=5, column=0, sticky=tk.W, pady=5)
        self.var_nthread = tk.StringVar(value=str(self.app.params.get("nthread", 0)))
        ttk.Entry(params_frame, textvariable=self.var_nthread, width=10).grid(row=5, column=1, sticky=tk.W, padx=10)

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
            self.var_kv.set(str(int(self.state.acc_voltage)))
            
        if self.state.h5_path and self.state.scan_name:
            import glob
            basename = os.path.splitext(os.path.basename(self.state.h5_path))[0]
            map_name = getattr(self.state, 'map_name', 'Map')
            bw = self.var_bw.get()
            
            # UP1 Naming
            up1_name = f"{basename}_{map_name}.up1"
            self.var_up1_name.set(up1_name)
            
            # NML Naming (increment integer if exists)
            base_nml_prefix = f"{basename}_{map_name}_BW{bw}"
            h5_dir = os.path.dirname(self.state.h5_path)
            
            # Check existing to increment
            existing_nmls = glob.glob(os.path.join(h5_dir, f"{base_nml_prefix}*.nml"))
            if not existing_nmls:
                final_nml = f"{base_nml_prefix}.nml"
            else:
                max_idx = 0
                import re
                pattern = re.compile(re.escape(base_nml_prefix) + r'_(\d+)\.nml$')
                for f in existing_nmls:
                    fname = os.path.basename(f)
                    if fname == f"{base_nml_prefix}.nml":
                        continue
                    match = pattern.search(fname)
                    if match:
                        max_idx = max(max_idx, int(match.group(1)))
                final_nml = f"{base_nml_prefix}_{max_idx + 1}.nml"
                
            self.var_nml_name.set(final_nml)

    def fetch_sht(self):
        element = self.var_element.get().strip().lower()
        struct_type = self.var_struct.get().strip().lower()
        kv = self.var_kv.get().strip()
        
        if not element or not struct_type or not kv:
            messagebox.showwarning("Missing Data", "Please fill in Element, Structure, and kV.")
            return
            
        tokens = [element, struct_type, f"{{{kv}kv}}".lower()]
        local_dir = os.path.join(utils.SCRIPT_DIR, self.app.config.get("sht_library_dir", "SHT_Library"))
        os.makedirs(local_dir, exist_ok=True)
        
        for local_file in os.listdir(local_dir):
            if local_file.endswith('.sht') and all(t in local_file.lower() for t in tokens):
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
                    basename = os.path.basename(path).lower()
                    if all(t in basename for t in tokens):
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
        if os.path.exists(out_up1):
            msg = f"The UP1 file already exists:\n{out_up1}\n\nDo you want to use the existing file (Yes) or overwrite and generate a new one (No)?"
            ans = messagebox.askyesnocancel("UP1 Exists", msg)
            if ans is None:
                return # Cancelled
            elif ans:
                skip_up1 = True # Yes, use existing
            else:
                skip_up1 = False # No, overwrite

        if os.path.exists(out_nml):
            msg = f"The NML file already exists.\n\nDo you want to overwrite it?"
            if not messagebox.askyesno("File Exists", msg):
                return

        try:
            bw = int(self.var_bw.get())
            native_delta = float(self.var_delta.get())
            gausbckg = self.var_gausbckg.get()
            nthread = int(self.var_nthread.get())
            
            nregions = int(self.var_nregions.get()) if gausbckg else 0
            
            self.app.params["bw"] = bw
            self.app.params["nregions"] = nregions
            self.app.params["native_delta"] = native_delta
            self.app.params["nthread"] = nthread
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

        wsl_maps = self.app.config.get("wsl_drive_mappings", {})
        write_up1 = utils.to_wsl_path(out_up1, wsl_maps)
        wsl_master_paths = [utils.to_wsl_path(p, wsl_maps) for p in sht_paths]
        masterfile_str = ",".join(f"'{p}'" for p in wsl_master_paths) + ","
        write_out = utils.to_wsl_path(out_nml, wsl_maps)
        base_out = os.path.splitext(write_out)[0]

        try:
            with open(out_nml, "w", newline='\n') as f_nml:
                f_nml.write(" &EMSphInx\n")
                f_nml.write("!#################################################################\n")
                f_nml.write("! Input Files\n")
                f_nml.write("!#################################################################\n")
                f_nml.write(f" patfile    = '{write_up1}',\n\n")
                f_nml.write(f" masterfile = {masterfile_str}\n\n")
                f_nml.write("!#################################################################\n")
                f_nml.write("! Pattern Processing\n")
                f_nml.write("!#################################################################\n")
                f_nml.write(f" patdims    = {self.state.pat_w}, {self.state.pat_h},\n")
                f_nml.write(" circmask   = -1,\n")
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
                f_nml.write(f" scandims   = {self.state.nx}, {self.state.ny}, {self.state.step_size},\n")
                f_nml.write(f" roimask    = {roi_str},\n\n")
                f_nml.write("!#################################################################\n")
                f_nml.write("! Indexing Parameters\n")
                f_nml.write("!#################################################################\n")
                f_nml.write(f" bw         = {bw},\n")
                f_nml.write(" normed     = .FALSE.,\n")
                f_nml.write(" refine     = .TRUE.,\n")
                f_nml.write(f" nthread    = {nthread},\n")
                f_nml.write(" batchsize  = 0,\n\n")
                f_nml.write("!#################################################################\n")
                f_nml.write("! Output Files\n")
                f_nml.write("!#################################################################\n")
                f_nml.write(f" datafile   = '{base_out}.h5',\n")
                f_nml.write(f" vendorfile = '{base_out}.ang',\n")
                f_nml.write(f" ipfmap     = '{base_out}_ipf.png',\n")
                f_nml.write(f" qualmap    = '{base_out}_q.png'\n")
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
        
        if out_up1 in self.app.shared_state.up1_tasks:
            self.app.shared_state.up1_tasks[out_up1]["jobs"].append(job_config)
            self.app.notebook.select(self.app.tab_queue)
        elif not skip_up1:
            self.app.shared_state.up1_tasks[out_up1] = {"mem": req_mem, "jobs": [job_config]}
            threading.Thread(target=self._worker_generate_up1, args=(out_up1, self.state.h5_path, self.state.scan_name), daemon=True).start()
            self.app.notebook.select(self.app.tab_queue)

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
                    chunk_size = max(1, (100 * 1024 * 1024) // bytes_per_pattern)
                    
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
