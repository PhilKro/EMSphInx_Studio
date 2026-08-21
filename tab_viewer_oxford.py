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
from oxford_metadata import normalize_beam_voltage_kv, normalize_step_size_um

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
        self.current_map_image = None
        self.map_data_2d = None 
        self.map_canvas_img_item = None
        self.map_cursor_item = None
        self.roi_canvas_item = None
        self.scans_cache = {}
        
        self.roi_start_x = 0
        self.roi_start_y = 0
        self.roi_drag_active = False
        
        self._setup_ui()

    def _setup_ui(self):
        pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True)

        left_scroll = utils.ScrollableFrame(pane)
        pane.add(left_scroll, weight=1)
        left_panel = ttk.Frame(left_scroll.scrollable_frame, padding=10)
        left_panel.pack(fill=tk.BOTH, expand=True)
        center_panel = ttk.Frame(pane, width=400)
        pane.add(center_panel, weight=2)
        right_panel = ttk.Frame(pane, width=400)
        pane.add(right_panel, weight=2)

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
        self.combo_pat_type.bind("<<ComboboxSelected>>", self.on_pattern_type_select)
        
        self.var_pat_row_major = tk.BooleanVar(value=True)
        ttk.Checkbutton(lf_files, text="Pattern Pixel Read: Row-Major", variable=self.var_pat_row_major, command=self.on_row_major_toggle).pack(anchor=tk.W, pady=(10, 0))
        self.var_map_row_major = tk.BooleanVar(value=True)
        ttk.Checkbutton(lf_files, text="Map Grid Read: Row-Major", variable=self.var_map_row_major, command=self.on_row_major_toggle).pack(anchor=tk.W)

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
        self.map_canvas.bind("<Configure>", self.on_map_canvas_resize)
        
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
                        step = normalize_step_size_um(
                            utils.get_h5_scalar(header["X Step"])
                        )
                        kv = normalize_beam_voltage_kv(
                            utils.get_h5_scalar(header.get("Beam Voltage", 20.0))
                        )
                        
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
            
            self.init_viewer()

    def on_row_major_toggle(self):
        if self.h5_file is not None:
            self.init_viewer()

    def on_pattern_type_select(self, event=None):
        if self.h5_file is None or not self.state.scan_name:
            return
        try:
            dataset = self.h5_file[self.state.scan_name]["Data"][
                self.var_pat_type.get()
            ]
            self.state.pat_h, self.state.pat_w = dataset.shape[-2:]
            self.lbl_pat_dims.config(
                text=f"Pattern Dims: {self.state.pat_w} x {self.state.pat_h}"
            )
            if hasattr(self.app, 'tab_nml_oxford'):
                self.app.tab_nml_oxford.update_h5_data()
            self.update_pattern_image()
        except (KeyError, ValueError) as e:
            messagebox.showerror("Pattern Selection Error", str(e))

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
        self.current_map_image = img_pil
        cw, ch = self.map_canvas.winfo_width(), self.map_canvas.winfo_height()
        new_w, new_h, self.map_offset_x, self.map_offset_y = utils.centered_fit_geometry(
            img_pil.width, img_pil.height, max(1, cw), max(1, ch)
        )
        self.map_scale_x, self.map_scale_y = new_w / img_pil.width, new_h / img_pil.height
        self.tk_img_map = ImageTk.PhotoImage(img_pil.resize((new_w, new_h), Image.Resampling.NEAREST))
        
        if self.map_canvas_img_item is None:
            self.map_canvas_img_item = self.map_canvas.create_image(
                self.map_offset_x, self.map_offset_y, image=self.tk_img_map, anchor=tk.NW
            )
        else:
            self.map_canvas.itemconfig(self.map_canvas_img_item, image=self.tk_img_map)
            self.map_canvas.coords(
                self.map_canvas_img_item, self.map_offset_x, self.map_offset_y
            )

    def on_map_canvas_resize(self, event):
        if self.current_map_image is None:
            return
        self.draw_map_image(self.current_map_image)
        self.update_map_cursor()
        self.draw_roi_from_state()

    def refresh_view(self):
        self.update_pattern_image()

    def on_slide(self, event=None):
        self.update_pattern_image()

    def on_map_click(self, event):
        if self.map_data_2d is not None: self.update_xy_from_click(event.x, event.y)

    def on_map_drag(self, event):
        if self.map_data_2d is not None: self.update_xy_from_click(event.x, event.y)

    def update_xy_from_click(self, cx, cy):
        grid_point = utils.canvas_to_grid_point(
            cx, cy, self.map_offset_x, self.map_offset_y,
            self.map_scale_x, self.map_scale_y, self.state.nx, self.state.ny,
        )
        if grid_point is None:
            return
        grid_x, grid_y = grid_point
        self.var_x.set(grid_x); self.var_y.set(grid_y)
        self.update_pattern_image()

    def draw_roi_from_state(self):
        if not hasattr(self, 'map_scale_x'): return
        if not self.state.use_roi:
            if getattr(self, 'roi_canvas_item', None):
                self.map_canvas.delete(self.roi_canvas_item)
                self.roi_canvas_item = None
            if getattr(self, 'roi_text_item', None):
                self.map_canvas.delete(self.roi_text_item)
                self.roi_text_item = None
            return
            
        x0, y0, w, h = self.state.roi
        x0 = max(0, min(self.state.nx - 1, x0))
        y0 = max(0, min(self.state.ny - 1, y0))
        w = max(1, min(self.state.nx - x0, w))
        h = max(1, min(self.state.ny - y0, h))
        
        x1 = self.map_offset_x + x0 * self.map_scale_x
        y1 = self.map_offset_y + y0 * self.map_scale_y
        x2 = self.map_offset_x + (x0 + w) * self.map_scale_x
        y2 = self.map_offset_y + (y0 + h) * self.map_scale_y
        
        if getattr(self, 'roi_canvas_item', None):
            self.map_canvas.coords(self.roi_canvas_item, x1, y1, x2, y2)
        else:
            self.roi_canvas_item = self.map_canvas.create_rectangle(x1, y1, x2, y2, outline='cyan', width=2, dash=(4, 4))
            
        text_label = f"({x0},{y0} {w}x{h})"
        text_y = y1 - 5 if y1 > 15 else y2 + 15
        if getattr(self, 'roi_text_item', None):
            self.map_canvas.coords(self.roi_text_item, x1, text_y)
            self.map_canvas.itemconfig(self.roi_text_item, text=text_label)
        else:
            self.roi_text_item = self.map_canvas.create_text(x1, text_y, text=text_label, fill="cyan", anchor=tk.SW, font=("Helvetica", 9, "bold"))

    def on_roi_press(self, event):
        if self.map_data_2d is None: return
        self.roi_drag_active = False
        if utils.canvas_to_grid_point(
            event.x, event.y, self.map_offset_x, self.map_offset_y,
            self.map_scale_x, self.map_scale_y, self.state.nx, self.state.ny,
        ) is None:
            return
        map_width = self.state.nx * self.map_scale_x
        map_height = self.state.ny * self.map_scale_y
        self.roi_start_x, self.roi_start_y = utils.clamp_canvas_point(
            event.x, event.y, self.map_offset_x, self.map_offset_y,
            map_width, map_height,
        )
        self.roi_drag_active = True
        if self.roi_canvas_item:
            self.map_canvas.delete(self.roi_canvas_item)
        self.roi_canvas_item = self.map_canvas.create_rectangle(self.roi_start_x, self.roi_start_y, event.x, event.y, outline='cyan', width=2, dash=(4, 4))

    def on_roi_drag(self, event):
        if self.roi_drag_active and self.roi_canvas_item:
            end_x, end_y = utils.clamp_canvas_point(
                event.x, event.y, self.map_offset_x, self.map_offset_y,
                self.state.nx * self.map_scale_x, self.state.ny * self.map_scale_y,
            )
            self.map_canvas.coords(self.roi_canvas_item, self.roi_start_x, self.roi_start_y, end_x, end_y)

    def on_roi_release(self, event):
        if not self.roi_drag_active or not self.roi_canvas_item: return
        self.roi_drag_active = False
        gx0, gy0, gw, gh = utils.canvas_roi_to_grid(
            self.roi_start_x, self.roi_start_y, event.x, event.y,
            self.map_offset_x, self.map_offset_y,
            self.map_scale_x, self.map_scale_y, self.state.nx, self.state.ny,
        )

        if gw > 0 and gh > 0:
            self.state.roi = (gx0, gy0, gw, gh)
            self.state.use_roi = True
            if hasattr(self.app, 'tab_nml_oxford'):
                self.app.tab_nml_oxford.update_roi_ui()
            self.lbl_pos.config(text=f"ROI Mapped: X0={gx0}, Y0={gy0}, W={gw}, H={gh}")
            self.draw_roi_from_state()
        else:
            if getattr(self, 'roi_canvas_item', None):
                self.map_canvas.delete(self.roi_canvas_item)
                self.roi_canvas_item = None
            if getattr(self, 'roi_text_item', None):
                self.map_canvas.delete(self.roi_text_item)
                self.roi_text_item = None
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
        
        self.update_map_cursor(x, y)

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

    def update_map_cursor(self, x=None, y=None):
        if not hasattr(self, 'map_scale_x'):
            return
        if x is None:
            x = int(round(self.var_x.get()))
        if y is None:
            y = int(round(self.var_y.get()))
        rect_x1 = self.map_offset_x + x * self.map_scale_x
        rect_y1 = self.map_offset_y + y * self.map_scale_y
        rect_x2 = self.map_offset_x + (x + 1) * self.map_scale_x
        rect_y2 = self.map_offset_y + (y + 1) * self.map_scale_y
        if self.map_cursor_item is None:
            self.map_cursor_item = self.map_canvas.create_rectangle(rect_x1, rect_y1, rect_x2, rect_y2, outline='red', width=2)
        else:
            self.map_canvas.coords(self.map_cursor_item, rect_x1, rect_y1, rect_x2, rect_y2)

    def draw_pat_canvas(self):
        if self.current_raw_image is None: return
        canvas_width = self.pat_canvas.winfo_width()
        canvas_height = self.pat_canvas.winfo_height()
        display_size = utils.fit_dimensions(
            self.current_raw_image.width,
            self.current_raw_image.height,
            canvas_width,
            canvas_height,
        )
        self.tk_img_pattern = ImageTk.PhotoImage(
            self.current_raw_image.resize(display_size, Image.Resampling.LANCZOS)
        )
        cx, cy = canvas_width // 2, canvas_height // 2
        if self.pat_canvas_img_item is None:
            self.pat_canvas_img_item = self.pat_canvas.create_image(cx, cy, image=self.tk_img_pattern, anchor=tk.CENTER)
        else:
            self.pat_canvas.itemconfig(self.pat_canvas_img_item, image=self.tk_img_pattern)
            self.pat_canvas.coords(self.pat_canvas_img_item, cx, cy)

    def on_pat_canvas_resize(self, event):
        self.draw_pat_canvas()
