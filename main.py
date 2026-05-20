import tkinter as tk
from tkinter import ttk, messagebox
import os

# Fix HDF5 Network Drive Bugs (eoa = 2048 / Link Iteration Failed)
os.environ["HDF5_USE_FILE_LOCKING"] = "FALSE"

import utils
from tab_viewer_edax import TabViewerEdax
from tab_nml_edax import TabNMLBuilderEdax
from tab_oxford import TabViewerOxford, TabNMLOxford
from tab_queue import TabQueue
from help_dialog import HelpDialog

class EMSphInxGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("EMSphInx Studio")
        self.root.geometry("1300x800")
        
        # Intercept the close action to handle WSL process safety
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        try:
            self.root.state('zoomed')
        except tk.TclError:
            try:
                self.root.attributes('-zoomed', True)
            except tk.TclError:
                pass 
        
        self.config = utils.load_json(utils.CONFIG_FILE, utils.DEFAULT_CONFIG)
        self.params = utils.load_json(utils.PARAMS_FILE, utils.DEFAULT_PARAMS)
        
        sht_dir_abs = os.path.abspath(os.path.join(utils.SCRIPT_DIR, self.config.get("sht_library_dir", "SHT_Library")))
        if ' ' in sht_dir_abs:
            messagebox.showwarning("Space in Path Warning",
                f"The SHT Library directory path contains spaces:\n{sht_dir_abs}\n\n"
                "EMSphInx will fail to read multiple master patterns if the path contains spaces. "
                "Consider moving this application to a path without spaces.")

        self.shared_state = utils.SharedState()
        self._setup_ui()

    def _setup_ui(self):
        # Create Menu Bar
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="EMSphInx Studio Help", command=self.show_help)

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
        """Handle application close gracefully to prevent WSL zombie processes and partial UP1 files."""
        is_queue_running = self.tab_queue.thread and self.tab_queue.thread.is_alive()
        is_up1_writing = bool(self.shared_state.up1_tasks)
        
        if is_queue_running or is_up1_writing:
            msg = "Background tasks are currently running (Queue or UP1 Generation).\n\nDo you want to abort them and exit the application?"
            if messagebox.askokcancel("Running Tasks Detected", msg):
                self.tab_queue.stop_flag = True
                if self.tab_queue.current_process:
                    try:
                        self.tab_queue.current_process.kill()
                    except Exception:
                        pass
                
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

if __name__ == "__main__":
    root = tk.Tk()
    style = ttk.Style()
    if 'clam' in style.theme_names():
        style.theme_use('clam')
    app = EMSphInxGUI(root)
    root.mainloop()