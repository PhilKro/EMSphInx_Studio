import os
import json
import re
import ctypes

class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_uint32),
        ("dwMemoryLoad", ctypes.c_uint32),
        ("ullTotalPhys", ctypes.c_uint64),
        ("ullAvailPhys", ctypes.c_uint64),
        ("ullTotalPageFile", ctypes.c_uint64),
        ("ullAvailPageFile", ctypes.c_uint64),
        ("ullTotalVirtual", ctypes.c_uint64),
        ("ullAvailVirtual", ctypes.c_uint64),
        ("sullAvailExtendedVirtual", ctypes.c_uint64),
    ]
    def __init__(self):
        self.dwLength = ctypes.sizeof(self)
        super(MEMORYSTATUSEX, self).__init__()

def get_available_memory():
    """Returns the available physical memory on Windows in bytes. Returns 8GB fallback if not on Windows."""
    if os.name == 'nt':
        stat = MEMORYSTATUSEX()
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        return stat.ullAvailPhys
    return 8 * 1024 * 1024 * 1024

import tkinter as tk
from tkinter import ttk

class ScrollableFrame(ttk.Frame):
    def __init__(self, container, *args, **kwargs):
        super().__init__(container, *args, **kwargs)
        
        self.canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        
        self.scrollable_frame = ttk.Frame(self.canvas)
        
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(
                scrollregion=self.canvas.bbox("all")
            )
        )
        
        self.canvas_window = self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        
        self.canvas.bind("<Enter>", self._bound_to_mousewheel)
        self.canvas.bind("<Leave>", self._unbound_to_mousewheel)
        self.scrollable_frame.bind("<Enter>", self._bound_to_mousewheel)
        self.scrollable_frame.bind("<Leave>", self._unbound_to_mousewheel)

    def _on_canvas_configure(self, event):
        if self.scrollable_frame.winfo_reqwidth() < event.width:
            self.canvas.itemconfig(self.canvas_window, width=event.width)
            
    def _bound_to_mousewheel(self, event):
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        
    def _unbound_to_mousewheel(self, event):
        self.canvas.unbind_all("<MouseWheel>")
        
    def _on_mousewheel(self, event):
        if event.delta:
            self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")



SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "app_config.json")
PARAMS_FILE = os.path.join(SCRIPT_DIR, "last_params.json")
DEFAULTS_FILE = os.path.join(SCRIPT_DIR, "defaults.json")
DEFAULT_CONFIG_FILE = os.path.join(SCRIPT_DIR, "default_app_config.json")

DEFAULT_CONFIG = {
    "wsl_distro": "Debian",
    "wsl_executable_dir": "/mnt/c/Software/EMSphInx",
    "sht_library_dir": "SHT_Library",
    "wsl_drive_mappings": {},
    "wsl_network_mounts": {},
    "wsl_sudo_password": ""
}

DEFAULT_PARAMS = {
    "system_mode": "EDAX",
    "OXFORD": {
        "gausbckg": False,
        "nregions": 0,
        "bw": 123,
        "nthread": 0,
        "batchsize": 0
    },
    "EDAX": {
        "gausbckg": True,
        "nregions": 10,
        "bw": 123,
        "native_delta": 23.0,
        "nthread": 0,
        "batchsize": 0
    }
}

def deep_update(d, u):
    for k, v in u.items():
        if isinstance(v, dict):
            d[k] = deep_update(d.get(k, {}), v)
        else:
            d[k] = v
    return d

def load_params():
    # 1. Create/Load defaults.json
    defaults = DEFAULT_PARAMS.copy()
    if os.path.exists(DEFAULTS_FILE):
        try:
            with open(DEFAULTS_FILE, 'r') as f:
                deep_update(defaults, json.load(f))
        except Exception as e:
            print(f"Error loading {DEFAULTS_FILE}: {e}")
    else:
        save_json(DEFAULTS_FILE, defaults)
        
    # 2. Load last_params.json over the defaults
    params = defaults.copy()
    if os.path.exists(PARAMS_FILE):
        try:
            with open(PARAMS_FILE, 'r') as f:
                deep_update(params, json.load(f))
        except Exception as e:
            print(f"Error loading {PARAMS_FILE}: {e}")
            
    # Always save merged params back
    save_json(PARAMS_FILE, params)
    return params

def get_current_user():
    try:
        import getpass
        return getpass.getuser()
    except Exception:
        return "default_user"

def get_local_drives():
    import string
    drives = {}
    for d in string.ascii_uppercase:
        if os.path.exists(d + ':\\'):
            # Only add to local drives if it's not a network drive
            if get_connection(d) is None:
                drives[f"{d}:"] = f"/mnt/{d.lower()}"
    return drives

def get_connection(drive):
    import ctypes
    from ctypes import wintypes
    mpr = ctypes.windll.mpr
    length = wintypes.DWORD(1024)
    buffer = ctypes.create_unicode_buffer(1024)
    res = mpr.WNetGetConnectionW(f'{drive}:', buffer, ctypes.byref(length))
    if res == 0:
        return buffer.value
    return None

def get_network_drives():
    import string
    network_mounts = {}
    drive_mappings = {}

    for d in string.ascii_uppercase:
        if os.path.exists(d + ':\\'):
            unc = get_connection(d)
            if unc:
                wsl_mnt = f"/mnt/{d.lower()}"
                network_mounts[wsl_mnt] = unc
                drive_mappings[f"{d}:"] = wsl_mnt
                
    return drive_mappings, network_mounts

def load_json(filepath, defaults):
    merged = defaults.copy()
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r') as f:
                merged.update(json.load(f))
        except Exception as e:
            print(f"Error loading {filepath}: {e}")
    save_json(filepath, merged)
    return merged

def save_json(filepath, data):
    try:
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"Error saving {filepath}: {e}")

def to_wsl_path(win_path, wsl_mappings, network_mounts=None):
    if not win_path: return win_path
    if network_mounts is None:
        network_mounts = {}
        
    win_path_fwd = win_path.replace('\\', '/')
    
    for mnt_point, unc_path in network_mounts.items():
        unc_fwd = unc_path.replace('\\', '/')
        if win_path_fwd.lower().startswith(unc_fwd.lower()):
            tail = win_path_fwd[len(unc_fwd):].lstrip('/')
            return f"{mnt_point}/{tail}"

    drive, tail = os.path.splitdrive(win_path)
    if not drive: return win_path.replace('\\', '/')
    drive_upper = drive.upper()
    
    if drive_upper in wsl_mappings:
        mnt_path = wsl_mappings[drive_upper]
    elif drive_upper == 'N:':
        mnt_path = '/mnt/n/RawData'
    elif drive_upper == 'D:':
        mnt_path = '/mnt/d'
    else:
        mnt_path = f"/mnt/{drive_upper[0].lower()}"
        
    tail = tail.replace('\\', '/').lstrip('/')
    return f"{mnt_path}/{tail}"

def to_windows_path(wsl_path, wsl_mappings, network_mounts=None):
    """Reverses WSL path back to Windows to check if files exist locally."""
    if network_mounts is None:
        network_mounts = {}
        
    for mnt_point, unc_path in network_mounts.items():
        if wsl_path.startswith(mnt_point):
            tail = wsl_path[len(mnt_point):].lstrip('/')
            tail_win = tail.replace('/', os.sep)
            return f"{unc_path}{os.sep}{tail_win}"

    rev_map = {v: k for k, v in wsl_mappings.items()}

    for w_prefix in sorted(rev_map.keys(), key=len, reverse=True):
        if wsl_path.startswith(w_prefix):
            win_drive = rev_map[w_prefix]
            tail = wsl_path[len(w_prefix):].lstrip('/')

            tail_win = tail.replace('/', os.sep)
            return f"{win_drive}{os.sep}{tail_win}"

    m = re.match(r'^/mnt/([a-z])/(.*)', wsl_path)
    if m:
        drive = m.group(1).upper() + ':'
        tail = m.group(2).replace('/', os.sep)
        return f"{drive}{os.sep}{tail}"

    return wsl_path

def sanitize_sht_filename(filename):
    name, ext = os.path.splitext(filename)
    clean_name = re.sub(r'[\s\(\)\[\]\{\}]+', '_', name)
    clean_name = clean_name.strip('_')
    return clean_name + ext

def get_h5_scalar(dataset):
    val = dataset[()]
    if hasattr(val, '__iter__') and not isinstance(val, str):
        return val[0]
    return val

class SharedState:
    def __init__(self):
        self.h5_path = ""
        self.up1_path = ""
        self.scan_name = ""
        self.nx = 0
        self.ny = 0
        self.pat_w = 0
        self.pat_h = 0
        self.byte_start = 16
        self.step_size = 1.0
        self.acc_voltage = 30.0 
        self.pc = (0.5, 0.5, 0.5) 
        self.use_roi = False
        self.roi = (0, 0, 0, 0)
        self.up1_tasks = {} # Tracks currently writing UP1 files and their mem reqs/dependent jobs