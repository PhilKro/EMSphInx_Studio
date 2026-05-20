import tkinter as tk
from tkinter import ttk
import json
import os
import utils

class HelpDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("EMSphInx Studio Help")
        self.geometry("800x500")
        self.minsize(600, 400)
        
        self.help_data = {}
        self._load_help_data()
        self._setup_ui()
        
    def _load_help_data(self):
        json_path = os.path.join(utils.SCRIPT_DIR, "help.json")
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                self.help_data = json.load(f)
        except Exception as e:
            self.help_data = {"Error": f"Could not load help data:\n{e}"}
            
    def _setup_ui(self):
        # Create a PanedWindow to separate the sidebar from the content
        pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Sidebar: Listbox for categories
        sidebar_frame = ttk.Frame(pane, width=200)
        pane.add(sidebar_frame, weight=1)
        
        ttk.Label(sidebar_frame, text="Contents", font=("Helvetica", 12, "bold")).pack(anchor=tk.W, pady=(0, 5))
        
        self.listbox = tk.Listbox(sidebar_frame, font=("Helvetica", 10), selectbackground="#0078D7", selectforeground="white", activestyle="none")
        self.listbox.pack(fill=tk.BOTH, expand=True)
        self.listbox.bind("<<ListboxSelect>>", self._on_select)
        
        # Content: Text widget for help text
        content_frame = ttk.Frame(pane)
        pane.add(content_frame, weight=4)
        
        self.text_viewer = tk.Text(content_frame, wrap=tk.WORD, font=("Helvetica", 10), state=tk.DISABLED, bg=self.cget('bg'), relief=tk.FLAT)
        
        scrollbar = ttk.Scrollbar(content_frame, orient=tk.VERTICAL, command=self.text_viewer.yview)
        self.text_viewer.configure(yscrollcommand=scrollbar.set)
        
        self.text_viewer.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 0))
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Populate Listbox
        for key in self.help_data.keys():
            self.listbox.insert(tk.END, key)
            
        # Select first item by default
        if self.help_data:
            self.listbox.selection_set(0)
            self._on_select(None)
            
    def _on_select(self, event):
        selection = self.listbox.curselection()
        if not selection:
            return
            
        key = self.listbox.get(selection[0])
        content = self.help_data.get(key, "No content available.")
        
        self.text_viewer.config(state=tk.NORMAL)
        self.text_viewer.delete("1.0", tk.END)
        
        # Apply formatting (bolding titles, handling bullet points)
        self.text_viewer.tag_configure("title", font=("Helvetica", 14, "bold"), foreground="#003366")
        self.text_viewer.tag_configure("bullet", lmargin1=20, lmargin2=40, spacing1=5)
        self.text_viewer.tag_configure("normal", lmargin1=0, lmargin2=0, spacing1=5)
        
        self.text_viewer.insert(tk.END, key + "\n\n", "title")
        
        lines = content.split('\n')
        for line in lines:
            if line.startswith('•') or line.startswith('-'):
                self.text_viewer.insert(tk.END, line + "\n", "bullet")
            else:
                self.text_viewer.insert(tk.END, line + "\n", "normal")
                
        self.text_viewer.config(state=tk.DISABLED)
