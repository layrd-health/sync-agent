"""First-run setup wizard using tkinter with modern styling."""

import logging
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

from PIL import Image, ImageTk, ImageDraw

from .database import Database

logger = logging.getLogger(__name__)

WINDOW_WIDTH = 540
WINDOW_HEIGHT = 580

# Brand colors
BG = "#f8f9fb"
CARD_BG = "#ffffff"
ACCENT = "#334155"
ACCENT_HOVER = "#475569"
ACCENT_LIGHT = "#647FBC"
TEXT_PRIMARY = "#1e293b"
TEXT_SECONDARY = "#64748b"
TEXT_MUTED = "#94a3b8"
BORDER = "#e2e8f0"
INPUT_BG = "#ffffff"
LIST_BG = "#f1f5f9"
LIST_SELECT = "#dbeafe"
DANGER = "#ef4444"

if getattr(sys, "frozen", False):
    ASSETS_DIR = Path(sys._MEIPASS) / "layrd_sync" / "assets"
else:
    ASSETS_DIR = Path(__file__).parent / "assets"


def _render_logo_image(size: int = 48) -> Image.Image:
    """Render the Layrd logo at the given pixel size with 4x supersampling."""
    ss = 4
    big = size * ss
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    padding = int(big * 0.05)
    logo_size = big - 2 * padding
    vb_x, vb_y, vb_w = 70, 70, 160
    s = logo_size / vb_w
    dark, light = ACCENT, ACCENT_LIGHT
    rects = [
        (100, 70, 40, 70, 20, dark),
        (70, 160, 70, 40, 20, dark),
        (100, 160, 40, 70, 20, light),
        (70, 100, 70, 40, 20, light),
        (160, 100, 70, 40, 20, dark),
        (160, 70, 40, 70, 20, light),
        (160, 160, 40, 70, 20, dark),
        (160, 160, 70, 40, 20, light),
    ]
    for rx, ry, rw, rh, rr, fill in rects:
        x0 = padding + (rx - vb_x) * s
        y0 = padding + (ry - vb_y) * s
        x1 = x0 + rw * s
        y1 = y0 + rh * s
        r = rr * s
        draw.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=fill)
    return img.resize((size, size), Image.LANCZOS)


def _apply_modern_style(root: tk.Tk):
    """Configure ttk styles for a clean, modern look."""
    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure(".", font=("Segoe UI", 10), background=BG, foreground=TEXT_PRIMARY)

    style.configure("Card.TFrame", background=CARD_BG)
    style.configure("BG.TFrame", background=BG)

    style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"),
                    background=BG, foreground=TEXT_PRIMARY)
    style.configure("Subtitle.TLabel", font=("Segoe UI", 10),
                    background=BG, foreground=TEXT_SECONDARY)
    style.configure("Section.TLabel", font=("Segoe UI", 10, "bold"),
                    background=CARD_BG, foreground=TEXT_PRIMARY)
    style.configure("Hint.TLabel", font=("Segoe UI", 9),
                    background=CARD_BG, foreground=TEXT_MUTED)
    style.configure("Card.TLabel", background=CARD_BG, foreground=TEXT_PRIMARY)

    style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"),
                    background=ACCENT, foreground="#ffffff",
                    borderwidth=0, padding=(16, 8), focuscolor="")
    style.map("Accent.TButton",
              background=[("active", ACCENT_HOVER), ("pressed", ACCENT_HOVER)],
              foreground=[("active", "#ffffff"), ("pressed", "#ffffff")])

    style.configure("Flat.TButton", font=("Segoe UI", 9),
                    background=CARD_BG, foreground=TEXT_PRIMARY,
                    borderwidth=1, padding=(10, 5))
    style.map("Flat.TButton",
              background=[("active", LIST_BG)])

    style.configure("TEntry", fieldbackground=INPUT_BG, borderwidth=1,
                    padding=(8, 6))

    style.configure("TCombobox", fieldbackground=INPUT_BG, padding=(6, 4))

    style.configure("Card.TCheckbutton", background=CARD_BG, foreground=TEXT_PRIMARY,
                    font=("Segoe UI", 9))


class SetupWizard:
    """Modern setup wizard for Layrd Sync configuration."""

    def __init__(self, db: Database):
        self.db = db
        self.completed = False
        self._folders: list[tuple[str, str]] = []
        self._photo_refs: list = []

        self.root = tk.Tk()
        self.root.title("Layrd Sync")
        self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.root.resizable(False, False)
        self.root.configure(bg=BG)

        self._set_window_icon()
        _apply_modern_style(self.root)
        self._build_ui()
        self._center_window()

    def _set_window_icon(self):
        ico_path = ASSETS_DIR / "icon.ico"
        png_path = ASSETS_DIR / "icon.png"
        try:
            if sys.platform == "win32" and ico_path.exists():
                self.root.iconbitmap(str(ico_path))
            elif png_path.exists():
                icon_img = tk.PhotoImage(file=str(png_path))
                self.root.iconphoto(True, icon_img)
                self._photo_refs.append(icon_img)
        except Exception:
            logger.debug("Could not set window icon", exc_info=True)

    def _center_window(self):
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() // 2) - (WINDOW_WIDTH // 2)
        y = (self.root.winfo_screenheight() // 2) - (WINDOW_HEIGHT // 2)
        self.root.geometry(f"+{x}+{y}")

    def _build_ui(self):
        outer = ttk.Frame(self.root, style="BG.TFrame", padding=(24, 20))
        outer.pack(fill=tk.BOTH, expand=True)

        # Header with logo
        header = ttk.Frame(outer, style="BG.TFrame")
        header.pack(fill=tk.X, pady=(0, 16))

        logo_img = _render_logo_image(40)
        logo_photo = ImageTk.PhotoImage(logo_img)
        self._photo_refs.append(logo_photo)

        logo_label = ttk.Label(header, image=logo_photo, background=BG)
        logo_label.pack(side=tk.LEFT, padx=(0, 12))

        title_frame = ttk.Frame(header, style="BG.TFrame")
        title_frame.pack(side=tk.LEFT, fill=tk.Y)

        ttk.Label(title_frame, text="Layrd Sync", style="Title.TLabel").pack(anchor=tk.W)
        ttk.Label(title_frame, text="Configure your sync agent",
                  style="Subtitle.TLabel").pack(anchor=tk.W)

        # Separator
        sep = tk.Frame(outer, height=1, bg=BORDER)
        sep.pack(fill=tk.X, pady=(0, 16))

        # Card container
        card = ttk.Frame(outer, style="Card.TFrame", padding=20)
        card.pack(fill=tk.BOTH, expand=True)
        card.configure(borderwidth=1, relief="solid")

        # Server URL section
        ttk.Label(card, text="Server URL", style="Section.TLabel").pack(anchor=tk.W)
        ttk.Label(card, text="Layrd backend address (leave default for cloud).",
                  style="Hint.TLabel").pack(anchor=tk.W, pady=(1, 6))
        self.api_url_var = tk.StringVar(
            value=self.db.get_config("api_url", "https://api.thelayrd.com"))
        url_entry = ttk.Entry(card, textvariable=self.api_url_var)
        url_entry.pack(fill=tk.X, pady=(0, 12))

        # API Key section
        ttk.Label(card, text="API Key", style="Section.TLabel").pack(anchor=tk.W)
        ttk.Label(card, text="Your authentication key for the Layrd service.",
                  style="Hint.TLabel").pack(anchor=tk.W, pady=(1, 6))
        self.api_key_var = tk.StringVar(value=self.db.get_config("api_key", ""))
        key_entry = ttk.Entry(card, textvariable=self.api_key_var, show="\u2022")
        key_entry.pack(fill=tk.X, pady=(0, 16))

        # Watched folders section
        ttk.Label(card, text="Watched Folders", style="Section.TLabel").pack(anchor=tk.W)
        ttk.Label(card, text="Folders this agent monitors for new faxes and scans.",
                  style="Hint.TLabel").pack(anchor=tk.W, pady=(1, 6))

        list_frame = tk.Frame(card, bg=BORDER, bd=1, relief="solid")
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        inner_list = tk.Frame(list_frame, bg=LIST_BG)
        inner_list.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        self.folder_listbox = tk.Listbox(
            inner_list, height=5, font=("Segoe UI", 9),
            bg=LIST_BG, fg=TEXT_PRIMARY, selectbackground=LIST_SELECT,
            selectforeground=TEXT_PRIMARY, bd=0, highlightthickness=0,
            activestyle="none",
        )
        self.folder_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4, pady=4)

        scrollbar = ttk.Scrollbar(inner_list, orient=tk.VERTICAL, command=self.folder_listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.folder_listbox.config(yscrollcommand=scrollbar.set)

        for f in self.db.get_folders(enabled_only=False):
            self._folders.append((f.path, f.label))
            self.folder_listbox.insert(tk.END, f"  {f.label.upper()}  \u2502  {f.path}")

        btn_frame = ttk.Frame(card, style="Card.TFrame")
        btn_frame.pack(fill=tk.X, pady=(0, 12))

        self.label_var = tk.StringVar(value="fax")
        label_combo = ttk.Combobox(
            btn_frame, textvariable=self.label_var,
            values=["fax", "scan", "other"], width=7, state="readonly",
        )
        label_combo.pack(side=tk.LEFT, padx=(0, 6))

        ttk.Button(btn_frame, text="+ Add Folder", command=self._add_folder,
                   style="Flat.TButton").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(btn_frame, text="Remove", command=self._remove_folder,
                   style="Flat.TButton").pack(side=tk.LEFT)

        # Auto-start checkbox
        self.autostart_var = tk.BooleanVar(value=True)
        if sys.platform == "win32":
            ttk.Checkbutton(
                card, text="Start automatically when I log in",
                variable=self.autostart_var, style="Card.TCheckbutton",
            ).pack(anchor=tk.W, pady=(4, 0))

        # Footer with save button (tk.Button for reliable foreground color on Windows)
        footer = ttk.Frame(outer, style="BG.TFrame")
        footer.pack(fill=tk.X, pady=(16, 0))

        save_btn = tk.Button(
            footer, text="Save & Start", command=self._save,
            font=("Segoe UI", 10, "bold"), bg=ACCENT, fg="#ffffff",
            activebackground=ACCENT_HOVER, activeforeground="#ffffff",
            bd=0, padx=20, pady=8, cursor="hand2", relief="flat",
        )
        save_btn.pack(side=tk.RIGHT)

    def _add_folder(self):
        path = filedialog.askdirectory(title="Select a folder to watch")
        if not path:
            return
        label = self.label_var.get()
        for existing_path, _ in self._folders:
            if existing_path == path:
                messagebox.showinfo("Already Added", "This folder is already in the list.")
                return
        self._folders.append((path, label))
        self.folder_listbox.insert(tk.END, f"  {label.upper()}  \u2502  {path}")

    def _remove_folder(self):
        selection = self.folder_listbox.curselection()
        if not selection:
            return
        idx = selection[0]
        self.folder_listbox.delete(idx)
        self._folders.pop(idx)

    def _save(self):
        if not self._folders:
            messagebox.showerror("Missing Folders", "Add at least one folder to watch.")
            return

        api_url = self.api_url_var.get().strip()
        if api_url:
            self.db.set_config("api_url", api_url)

        api_key = self.api_key_var.get().strip()
        if api_key:
            self.db.set_config("api_key", api_key)

        existing = {f.path: f for f in self.db.get_folders(enabled_only=False)}
        new_paths = {path for path, _ in self._folders}

        for path, folder in existing.items():
            if path not in new_paths:
                self.db.remove_folder(folder.id)

        for path, label in self._folders:
            self.db.add_folder(path, label)

        if sys.platform == "win32":
            from .autostart import set_autostart
            set_autostart(self.autostart_var.get())

        self.db.set_config("setup_complete", "true")
        self.completed = True
        self.root.destroy()
        logger.info("Setup completed: folders=%d", len(self._folders))

    def run(self) -> bool:
        """Show the wizard. Returns True if setup was completed, False if window was closed."""
        self.root.mainloop()
        return self.completed
