"""Windows auto-start management via the Run registry key."""

import logging
import sys
import os

logger = logging.getLogger(__name__)

APP_NAME = "LayrdSync"
REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _get_exe_path() -> str:
    """Get the path to the current executable (works for both PyInstaller and dev)."""
    if getattr(sys, "frozen", False):
        return sys.executable
    return os.path.abspath(sys.argv[0])


def set_autostart(enabled: bool):
    """Add or remove LayrdSync from Windows startup."""
    if sys.platform != "win32":
        logger.debug("Auto-start is only supported on Windows")
        return

    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_SET_VALUE
        )

        if enabled:
            exe_path = _get_exe_path()
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{exe_path}"')
            logger.info("Auto-start enabled: %s", exe_path)
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
                logger.info("Auto-start disabled")
            except FileNotFoundError:
                pass

        winreg.CloseKey(key)

    except Exception as e:
        logger.warning("Failed to set auto-start: %s", e)


def is_autostart_enabled() -> bool:
    """Check if LayrdSync is in Windows startup."""
    if sys.platform != "win32":
        return False

    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_READ
        )
        try:
            winreg.QueryValueEx(key, APP_NAME)
            return True
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)

    except Exception:
        return False
