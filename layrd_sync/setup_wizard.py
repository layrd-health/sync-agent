"""First-run setup wizard using tkinter. Collects API URL and watched folders."""

import logging
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

from .database import Database

logger = logging.getLogger(__name__)

WINDOW_WIDTH = 520
WINDOW_HEIGHT = 480


class SetupWizard:
    """Simple tkinter GUI for first-run configuration."""

    def __init__(self, db: Database):
        self.db = db
        self.completed = False
        self._folders: list[tuple[str, str]] = []

        self.root = tk.Tk()
        self.root.title("Layrd Sync — Setup")
        self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.root.resizable(False, False)

        if sys.platform == "win32":
            self.root.attributes("-toolwindow", False)

        self._build_ui()
        self._center_window()

    def _center_window(self):
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() // 2) - (WINDOW_WIDTH // 2)
        y = (self.root.winfo_screenheight() // 2) - (WINDOW_HEIGHT // 2)
        self.root.geometry(f"+{x}+{y}")

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=20)
        main.pack(fill=tk.BOTH, expand=True)

        # Title
        title = ttk.Label(main, text="Welcome to Layrd Sync", font=("Segoe UI", 16, "bold"))
        title.pack(anchor=tk.W, pady=(0, 4))

        subtitle = ttk.Label(
            main,
            text="Configure your sync agent to watch folders and upload documents.",
            wraplength=460,
            foreground="#666",
        )
        subtitle.pack(anchor=tk.W, pady=(0, 16))

        # API URL
        ttk.Label(main, text="Backend URL", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W)
        ttk.Label(main, text="The Layrd server this agent uploads to.", foreground="#888", font=("Segoe UI", 8)).pack(anchor=tk.W)
        self.api_url_var = tk.StringVar(value=self.db.get_config("api_url", "http://localhost:8000"))
        api_entry = ttk.Entry(main, textvariable=self.api_url_var, width=60)
        api_entry.pack(anchor=tk.W, pady=(4, 12), fill=tk.X)

        # API Key
        ttk.Label(main, text="API Key (optional)", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W)
        self.api_key_var = tk.StringVar(value=self.db.get_config("api_key", ""))
        key_entry = ttk.Entry(main, textvariable=self.api_key_var, width=60, show="•")
        key_entry.pack(anchor=tk.W, pady=(4, 12), fill=tk.X)

        # Watched folders
        ttk.Label(main, text="Watched Folders", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W)
        ttk.Label(main, text="Add the fax and scan folders this agent should monitor.", foreground="#888", font=("Segoe UI", 8)).pack(anchor=tk.W)

        folder_frame = ttk.Frame(main)
        folder_frame.pack(fill=tk.BOTH, expand=True, pady=(4, 8))

        self.folder_listbox = tk.Listbox(folder_frame, height=5, font=("Segoe UI", 9))
        self.folder_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(folder_frame, orient=tk.VERTICAL, command=self.folder_listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.folder_listbox.config(yscrollcommand=scrollbar.set)

        # Pre-populate with existing folders
        for f in self.db.get_folders(enabled_only=False):
            self._folders.append((f.path, f.label))
            self.folder_listbox.insert(tk.END, f"[{f.label}] {f.path}")

        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=(0, 8))

        self.label_var = tk.StringVar(value="fax")
        label_combo = ttk.Combobox(btn_frame, textvariable=self.label_var, values=["fax", "scan", "other"], width=8, state="readonly")
        label_combo.pack(side=tk.LEFT, padx=(0, 4))

        ttk.Button(btn_frame, text="Add Folder…", command=self._add_folder).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(btn_frame, text="Remove", command=self._remove_folder).pack(side=tk.LEFT)

        # Auto-start checkbox
        self.autostart_var = tk.BooleanVar(value=True)
        if sys.platform == "win32":
            ttk.Checkbutton(main, text="Start automatically when I log in", variable=self.autostart_var).pack(anchor=tk.W, pady=(0, 12))

        # Save button
        save_btn = ttk.Button(main, text="Save & Start", command=self._save)
        save_btn.pack(anchor=tk.E, pady=(8, 0))

    def _add_folder(self):
        path = filedialog.askdirectory(title="Select a folder to watch")
        if not path:
            return
        label = self.label_var.get()
        for existing_path, _ in self._folders:
            if existing_path == path:
                messagebox.showinfo("Already Added", f"This folder is already in the list.")
                return
        self._folders.append((path, label))
        self.folder_listbox.insert(tk.END, f"[{label}] {path}")

    def _remove_folder(self):
        selection = self.folder_listbox.curselection()
        if not selection:
            return
        idx = selection[0]
        self.folder_listbox.delete(idx)
        self._folders.pop(idx)

    def _save(self):
        api_url = self.api_url_var.get().strip()
        if not api_url:
            messagebox.showerror("Error", "Backend URL is required.")
            return

        if not self._folders:
            messagebox.showerror("Error", "Add at least one watched folder.")
            return

        self.db.set_config("api_url", api_url)

        api_key = self.api_key_var.get().strip()
        if api_key:
            self.db.set_config("api_key", api_key)

        # Sync folders: remove old ones, add new ones
        existing = {f.path: f for f in self.db.get_folders(enabled_only=False)}
        new_paths = {path for path, _ in self._folders}

        for path, folder in existing.items():
            if path not in new_paths:
                self.db.remove_folder(folder.id)

        for path, label in self._folders:
            self.db.add_folder(path, label)

        # Auto-start
        if sys.platform == "win32":
            from .autostart import set_autostart
            set_autostart(self.autostart_var.get())

        self.db.set_config("setup_complete", "true")
        self.completed = True
        self.root.destroy()
        logger.info("Setup completed: api_url=%s, folders=%d", api_url, len(self._folders))

    def run(self) -> bool:
        """Show the wizard. Returns True if setup was completed, False if window was closed."""
        self.root.mainloop()
        return self.completed
