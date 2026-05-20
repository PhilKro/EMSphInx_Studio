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


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "app_config.json")
PARAMS_FILE = os.path.join(SCRIPT_DIR, "last_params.json")

DEFAULT_CONFIG = {
    "wsl_distro": "Debian",
    "wsl_executable_dir": "/mnt/c/Software/EMSphInx",
    "sht_library_dir": "SHT_Library",
    "wsl_drive_mappings": {"C:": "/mnt/c", "Z:": "/mnt/z/NetworkData"},
    "wsl_network_mounts": {"/mnt/z": "\\\\YOUR_SERVER\\ShareName"},
    "wsl_sudo_password": ""
}

DEFAULT_PARAMS = {
    "gausbckg": True,
    "nregions": 4,
    "bw": 123,
    "native_delta": 23.0,
    "nthread": 0
}

def load_json(filepath, defaults):
    merged = defaults.copy()
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
                merged.update(data)
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

def to_wsl_path(win_path, wsl_mappings):
    if not win_path: return win_path
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

def to_windows_path(wsl_path, wsl_mappings):
    """Reverses WSL path back to Windows to check if files exist locally."""
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