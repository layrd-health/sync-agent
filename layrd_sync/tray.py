"""System tray UI using pystray. Works on Windows, macOS, and Linux."""

import logging
import threading
import sys
from pathlib import Path

from PIL import Image, ImageDraw
import pystray

from . import __version__
from .database import Database
from .sync_engine import SyncEngine
from .updater import Updater

logger = logging.getLogger(__name__)


if getattr(sys, "frozen", False):
    ASSETS_DIR = Path(sys._MEIPASS) / "layrd_sync" / "assets"
else:
    ASSETS_DIR = Path(__file__).parent / "assets"


def _load_logo() -> Image.Image:
    """Render the Layrd logo inside a rounded white-ish box, sized for a tray icon."""
    size = 64
    padding = 8

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    logo_size = size - 2 * padding
    vb_x, vb_y, vb_w, vb_h = 70, 70, 160, 160
    s = logo_size / vb_w

    dark = "#d6dae0"
    light = "#8590a0"

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

    return img


class TrayApp:
    def __init__(
        self,
        db: Database,
        sync_engine: SyncEngine,
        updater: Updater | None = None,
    ):
        self.db = db
        self.sync_engine = sync_engine
        self.updater = updater
        self._icon: pystray.Icon | None = None
        self._status_text = "Idle"

    def _build_menu(self) -> pystray.Menu:
        stats = self.db.get_upload_stats()
        uploaded = stats.get("uploaded", 0)
        failed = stats.get("failed", 0)
        pending = stats.get("pending", 0)

        reconcile = self.sync_engine.last_reconcile
        if reconcile:
            inbox_count = reconcile.get("inbox_count", 0)
            active_count = reconcile.get("active_count", 0)
            files_line = f"Inbox: {inbox_count} files, {active_count} active in Layrd"
        else:
            files_line = f"Files: {uploaded} uploaded, {failed} failed, {pending} pending"

        folders = self.db.get_folders(enabled_only=False)
        folder_items = []
        for f in folders:
            folder_items.append(
                pystray.MenuItem(
                    f"  {f.label}: {f.path}",
                    None,
                    enabled=False,
                )
            )
        if not folder_items:
            folder_items.append(pystray.MenuItem("  (none configured)", None, enabled=False))

        return pystray.Menu(
            pystray.MenuItem(f"Layrd Sync v{__version__}", None, enabled=False),
            pystray.MenuItem(f"Status: {self._status_text}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(files_line, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Watched Folders:", None, enabled=False),
            *folder_items,
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Sync Now", self._on_sync_now),
            pystray.MenuItem(
                f"Retry Failed ({failed})" if failed else "Retry Failed",
                self._on_retry_failed,
                enabled=failed > 0,
            ),
            pystray.MenuItem("Check for Updates", self._on_check_update),
            pystray.MenuItem("Settings…", self._on_settings),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._on_quit),
        )

    def _on_sync_now(self, icon, item):
        self._status_text = "Syncing..."
        self._update_menu()
        thread = threading.Thread(target=self._run_sync, daemon=True)
        thread.start()

    def _run_sync(self):
        try:
            self.sync_engine.run_sync_cycle()
            self._status_text = "Idle"
        except Exception as e:
            logger.exception("Sync error")
            self._status_text = f"Error: {e}"
        self._update_menu()

    def _on_retry_failed(self, icon, item):
        self._status_text = "Retrying failed uploads..."
        self._update_menu()
        thread = threading.Thread(target=self._run_retry_failed, daemon=True)
        thread.start()

    def _run_retry_failed(self):
        try:
            count = self.sync_engine.retry_failed()
            if count > 0:
                self._status_text = f"Retried {count} file(s)"
            else:
                self._status_text = "No failed files to retry"
        except Exception as e:
            logger.exception("Retry error")
            self._status_text = f"Retry error: {e}"
        self._update_menu()

    def _on_check_update(self, icon, item):
        if not self.updater:
            return
        thread = threading.Thread(target=self._run_update_check, daemon=True)
        thread.start()

    def _run_update_check(self):
        info = self.updater.check_for_update()
        if info:
            self._status_text = f"Downloading update v{info['version']}..."
            self._update_menu()
            if self._icon:
                self._icon.notify(
                    f"Downloading Layrd Sync v{info['version']}...",
                    "Update Available",
                )
            if self.updater.download_and_apply(info):
                if self._icon:
                    self._icon.notify(
                        "Update installed. Restarting...",
                        "Update Complete",
                    )
                logger.info("Update applied via tray, stopping tray to let process exit")
                if self._icon:
                    self._icon.stop()
            else:
                self._status_text = "Update failed"
                self._update_menu()
                if self._icon:
                    self._icon.notify("Update download or install failed.", "Update Error")
        else:
            if self._icon:
                self._icon.notify("You're running the latest version.", "No Updates")

    def _on_settings(self, icon, item):
        thread = threading.Thread(target=self._run_settings, daemon=True)
        thread.start()

    def _run_settings(self):
        import subprocess
        if getattr(sys, "frozen", False):
            result = subprocess.run(
                [sys.executable, "--settings-only"],
                timeout=300,
            )
        else:
            result = subprocess.run(
                [sys.executable, "-m", "layrd_sync.settings_runner"],
                timeout=300,
            )
        if result.returncode == 0:
            self._update_menu()
            if self._icon:
                self._icon.notify("Settings saved.", "Settings Updated")

    def _on_quit(self, icon, item):
        logger.info("User requested quit")
        if self._icon:
            self._icon.stop()

    def _update_menu(self):
        if self._icon:
            self._icon.menu = self._build_menu()
            self._icon.update_menu()

    def update_status(self, text: str):
        self._status_text = text
        self._update_menu()

    def run(self):
        """Start the tray icon. Blocks until quit."""
        self._icon = pystray.Icon(
            name="layrd_sync",
            icon=_load_logo(),
            title=f"Layrd Sync v{__version__}",
            menu=self._build_menu(),
        )
        logger.info("Starting tray icon")
        self._icon.run()
