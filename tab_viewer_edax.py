import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import h5py
import os
import struct
import numpy as np
from PIL import Image, ImageTk
import utils

try:
    import matplotlib.cm as cm
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

class TabViewerEdax(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.state = app.shared_state
        
        self.mmap = None
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

        self.btn_load_h5 = ttk.Button(lf_files, text="Load .edaxh5 File", command=self.load_h5)
        self.btn_load_h5.pack(fill=tk.X, pady=(0, 5))

        ttk.Label(lf_files, text="Select map from H5:").pack(anchor=tk.W, pady=(5, 2))
        self.combo_scan = ttk.Combobox(lf_files, state="readonly", width=50)
        self.combo_scan.pack(fill=tk.X, pady=(0, 10))
        self.combo_scan.bind("<<ComboboxSelected>>", self.on_scan_select)

        self.btn_load_up1 = ttk.Button(lf_files, text="Load .up1 File", command=self.load_up1)
        self.btn_load_up1.pack(fill=tk.X, pady=(0, 5))
        self.lbl_up1_file = ttk.Label(lf_files, text="No UP1 loaded.", foreground="gray", wraplength=340)
        self.lbl_up1_file.pack(fill=tk.X)
        
        self.var_pat_row_major = tk.BooleanVar(value=True)
        ttk.Checkbutton(lf_files, text="Pattern Pixel Read: Row-Major", variable=self.var_pat_row_major, command=self.refresh_view).pack(anchor=tk.W, pady=(10, 0))
        self.var_map_row_major = tk.BooleanVar(value=True)
        ttk.Checkbutton(lf_files, text="Map Grid Read: Row-Major", variable=self.var_map_row_major, command=self.recalc_map).pack(anchor=tk.W)

        self.btn_init = ttk.Button(lf_files, text="Initialize Interactive Map", command=self.init_viewer)
        self.btn_init.pack(fill=tk.X, pady=(15, 0))

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
        self.var_map_field = tk.StringVar(value="Mean Intensity (Calculated)")
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

    def load_h5(self):
        filepath = filedialog.askopenfilename(filetypes=[("EDAX HDF5", "*.edaxh5 *.h5")])
        if not filepath: return
        self.state.h5_path = filepath
        self.scans_cache.clear()
        
        try:
            with h5py.File(filepath, 'r') as f:
                def visit_func(name, obj):
                    if isinstance(obj, h5py.Group) and "Sample/Number Of Columns" in obj:
                        nx = int(utils.get_h5_scalar(obj["Sample/Number Of Columns"]))
                        ny = int(utils.get_h5_scalar(obj["Sample/Number Of Rows"]))
                        step = float(utils.get_h5_scalar(obj.get("Sample/Step X", 1.0)))
                        
                        kv = 30.0
                        if "Electron Beam/SEMkV" in obj:
                            kv = float(utils.get_h5_scalar(obj["Electron Beam/SEMkV"]))
                            
                        pcx, pcy, pcz = 0.5, 0.5, 0.5
                        try:
                            pc_group = obj["EBSD/ANG/HEADER/Pattern Center Calibration"]
                            pcx = float(utils.get_h5_scalar(pc_group["X-Star"]))
                            pcy = float(utils.get_h5_scalar(pc_group["Y-Star"]))
                            pcz = float(utils.get_h5_scalar(pc_group["Z-Star"]))
                        except KeyError:
                            pass 

                        if nx > 0 and ny > 0:
                            map_fields = []
                            data_len = None
                            if "EBSD/ANG/DATA/DATA" in obj:
                                ds = obj["EBSD/ANG/DATA/DATA"]
                                data_len = ds.shape[0]
                                if ds.dtype.names:
                                    for n in ds.dtype.names:
                                        if n in ["IQ", "CI", "Phase", "SEM Signal"] or "PRIAS" in n:
                                            map_fields.append(n)

                            self.scans_cache[name] = {
                                "nx": nx, "ny": ny, "step": step, "kv": kv, "pc": (pcx, pcy, pcz),
                                "map_fields": map_fields, "data_len": data_len
                            }
                            
                f.visititems(visit_func)
            
            scans = sorted(list(self.scans_cache.keys()))
            if scans:
                self.combo_scan['values'] = scans
                self.combo_scan.current(0)
                self.on_scan_select(None)
            else:
                self.combo_scan['values'] = []
                self.combo_scan.set('')
                messagebox.showwarning("No Scans", "Could not find standard OIM Map scans.")
                
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
            
            fields = ["Mean Intensity (Calculated)"] + data.get("map_fields", [])
            self.combo_map_field['values'] = fields
            if self.var_map_field.get() not in fields:
                self.combo_map_field.current(0)
            
            self.app.tab_nml_edax.update_h5_data()

    def load_up1(self):
        start_dir = os.path.dirname(self.state.h5_path) if self.state.h5_path else os.getcwd()
        filepath = filedialog.askopenfilename(initialdir=start_dir, filetypes=[("EDAX Patterns", "*.up1")])
        if not filepath: return
            
        self.state.up1_path = filepath
        self.lbl_up1_file.config(text=os.path.basename(filepath))
        
        try:
            with open(filepath, 'rb') as f:
                header_bytes = f.read(16)
                header = struct.unpack('<4I', header_bytes)
                self.state.pat_w = header[1]
                self.state.pat_h = header[2]
                self.state.byte_start = header[3]
                self.lbl_pat_dims.config(text=f"Pattern Dims: {self.state.pat_w} x {self.state.pat_h}")
                
            if self.state.pat_w > 0 and self.state.pat_h > 0 and self.scans_cache:
                total_bytes = os.path.getsize(filepath)
                total_pats = (total_bytes - self.state.byte_start) // (self.state.pat_w * self.state.pat_h)
                
                for scan_name, dims in self.scans_cache.items():
                    h5_pats = dims.get("data_len")
                    if h5_pats is None:
                        h5_pats = dims["nx"] * dims["ny"]
                    if h5_pats == total_pats:
                        self.combo_scan.set(scan_name)
                        self.on_scan_select(None)
                        break

            self.app.tab_nml_edax.update_h5_data()

        except Exception as e:
            messagebox.showerror("Header Error", f"Could not read UP1 header:\n{e}")

    def init_viewer(self):
        if not self.state.up1_path or self.state.pat_w == 0:
            messagebox.showerror("Error", "Please load a valid .up1 file first.")
            return

        nx, ny = self.state.nx, self.state.ny
        expected_bytes = nx * ny * self.state.pat_w * self.state.pat_h
        actual_size = os.path.getsize(self.state.up1_path)
        
        if (actual_size - self.state.byte_start) != expected_bytes:
            resp = messagebox.askyesno("Size Warning", "File size mismatch. Map may look distorted.\nProceed?")
            if not resp: return

        try:
            self.mmap = np.memmap(self.state.up1_path, dtype='uint8', mode='r', offset=self.state.byte_start, shape=(nx * ny, self.state.pat_w * self.state.pat_h))
            self.scale_x.config(to=max(1, nx-1))
            self.scale_y.config(to=max(1, ny-1))
            self.var_x.set(0); self.var_y.set(0)
            self.scale_x.state(['!disabled']); self.scale_y.state(['!disabled'])
            self.pat_canvas.delete(self.placeholder_txt)
            self.recalc_map()
        except Exception as e:
            messagebox.showerror("Init Error", str(e))

    def recalc_map(self):
        if not self.state.nx or not self.state.ny: return
        field = self.var_map_field.get()
        if field == "Mean Intensity (Calculated)":
            if self.mmap is None: return
            step = max(1, (self.state.pat_w * self.state.pat_h) // 100)
            data_1d = np.mean(self.mmap[:, ::step], axis=1)
        else:
            if not self.state.h5_path: return
            try:
                with h5py.File(self.state.h5_path, 'r') as f:
                    ds = f[self.state.scan_name]["EBSD/ANG/DATA/DATA"]
                    data_1d = ds[field][:]
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
        
        if self.mmap is not None:
            self.update_pattern_image() 
        self.draw_roi_from_state()

    def draw_map_image(self, img_pil):
        self.map_canvas.update_idletasks()
        cw, ch = self.map_canvas.winfo_width(), self.map_canvas.winfo_height()
        if cw < 10: cw, ch = 350, 350
        
        img_aspect = img_pil.width / img_pil.height
        canvas_aspect = cw / ch
        
        if img_aspect > canvas_aspect:
            new_w = cw
            new_h = max(1, int(cw / img_aspect))
        else:
            new_h = ch
            new_w = max(1, int(ch * img_aspect))
            
        self.map_scale_x, self.map_scale_y = new_w / img_pil.width, new_h / img_pil.height
        self.tk_img_map = ImageTk.PhotoImage(img_pil.resize((new_w, new_h), Image.Resampling.NEAREST))
        
        if getattr(self, 'map_canvas_img_item', None) is None:
            self.map_canvas_img_item = self.map_canvas.create_image(0, 0, image=self.tk_img_map, anchor=tk.NW)
        else:
            self.map_canvas.itemconfig(self.map_canvas_img_item, image=self.tk_img_map)

    def refresh_view(self):
        if self.mmap is not None: self.update_pattern_image()

    def on_slide(self, event=None):
        if self.mmap is not None: self.update_pattern_image()

    def on_map_click(self, event):
        if self.map_data_2d is not None: self.update_xy_from_click(event.x, event.y)

    def on_map_drag(self, event):
        if self.map_data_2d is not None: self.update_xy_from_click(event.x, event.y)

    def update_xy_from_click(self, cx, cy):
        grid_x = max(0, min(self.state.nx - 1, int(cx / self.map_scale_x)))
        grid_y = max(0, min(self.state.ny - 1, int(cy / self.map_scale_y)))
        self.var_x.set(grid_x); self.var_y.set(grid_y)
        if self.mmap is not None:
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
        
        x1, y1 = x0 * self.map_scale_x, y0 * self.map_scale_y
        x2, y2 = (x0 + w) * self.map_scale_x, (y0 + h) * self.map_scale_y
        
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
        self.roi_start_x = event.x
        self.roi_start_y = event.y
        if getattr(self, 'roi_canvas_item', None):
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
        gx0 = max(0, min(self.state.nx - 1, int(grid_x1)))
        gy0 = max(0, min(self.state.ny - 1, int(grid_y1)))
        gw = max(1, min(self.state.nx - gx0, int(grid_x2 - grid_x1 + 0.5)))
        gh = max(1, min(self.state.ny - gy0, int(grid_y2 - grid_y1 + 0.5)))

        if gw > 0 and gh > 0:
            self.state.roi = (gx0, gy0, gw, gh)
            self.state.use_roi = True
            if hasattr(self.app, 'tab_nml_edax'):
                self.app.tab_nml_edax.update_roi_ui()
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
            if hasattr(self.app, 'tab_nml_edax'):
                self.app.tab_nml_edax.update_roi_ui()

    def get_1d_index(self, x, y):
        if self.var_map_row_major.get():
            return (y * self.state.nx) + x
        else:
            return (x * self.state.ny) + y

    def update_pattern_image(self):
        if self.mmap is None: return
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

        raw_1d = self.mmap[idx]
        pat_2d = raw_1d.reshape((self.state.pat_h, self.state.pat_w), order='C' if self.var_pat_row_major.get() else 'F')
            
        cmap = self.var_cmap.get()
        if cmap in ["Plasma", "Magma", "Rainbow"] and MATPLOTLIB_AVAILABLE:
            colored = getattr(cm, cmap.lower())(pat_2d / 255.0)
            self.current_raw_image = Image.fromarray((colored[:, :, :3] * 255).astype(np.uint8), mode='RGB')
        else:
            self.current_raw_image = Image.fromarray(pat_2d, mode='L')
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
        if self.mmap is not None: self.draw_pat_canvas()