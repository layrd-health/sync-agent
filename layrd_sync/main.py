"""Entry point — starts the scheduler and tray app."""

import argparse
import logging
import sys
import signal

from apscheduler.schedulers.background import BackgroundScheduler

from . import __version__
from .database import Database
from .sync_engine import SyncEngine
from .uploader import Uploader
from .updater import Updater
from .tray import TrayApp

logger = logging.getLogger("layrd_sync")

DEFAULT_POLL_INTERVAL = 30  # seconds
DEFAULT_UPDATE_CHECK_INTERVAL = 3600  # 1 hour


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _setup_heartbeat(db: Database, api_url: str, api_key: str | None):
    """Create heartbeat client and attach its log handler."""
    from .heartbeat import HeartbeatClient, HeartbeatLogHandler
    heartbeat = HeartbeatClient(db=db, api_url=api_url, api_key=api_key)
    handler = HeartbeatLogHandler(heartbeat)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logging.getLogger("layrd_sync").addHandler(handler)
    return heartbeat, handler


def _fetch_remote_config(db: Database, api_url: str, api_key: str | None) -> tuple[str, str | None]:
    """Check the server for config overrides (e.g. a new api_url).

    Returns the (possibly updated) api_url and api_key.  Failures are
    silently ignored so the agent always starts.
    """
    import httpx
    try:
        headers = {"X-API-Key": api_key} if api_key else {}
        resp = httpx.get(
            f"{api_url.rstrip('/')}/api/sync-agent/config",
            headers=headers,
            timeout=5,
        )
        if resp.status_code == 200:
            data = resp.json()
            new_url = data.get("api_url")
            if new_url and new_url != api_url:
                logger.info("Remote config: redirecting to %s", new_url)
                db.set_config("api_url", new_url)
                api_url = new_url
            new_key = data.get("api_key")
            if new_key and new_key != api_key:
                db.set_config("api_key", new_key)
                api_key = new_key
    except Exception:
        logger.debug("Remote config check skipped (server unreachable)")
    return api_url, api_key


def _needs_setup(db: Database) -> bool:
    """Check if first-run setup is needed."""
    return db.get_config("setup_complete") != "true"


def _run_setup(db: Database) -> bool:
    """Launch the setup wizard. Returns True if completed."""
    from .setup_wizard import SetupWizard
    wizard = SetupWizard(db)
    return wizard.run()


def main():
    parser = argparse.ArgumentParser(description="Layrd Document Sync Agent")
    parser.add_argument("--verbose", "-v", action="store_true", help="Debug logging")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--headless", action="store_true", help="Run without system tray (for testing)")
    parser.add_argument("--setup", action="store_true", help="Force the setup wizard to run")
    parser.add_argument("--settings-only", action="store_true",
                        help="Open settings wizard and exit (used internally by tray)")
    parser.add_argument("--add-folder", nargs=2, metavar=("PATH", "LABEL"),
                        help="Add a watched folder (e.g. --add-folder Z:\\ fax)")
    parser.add_argument("--api-url", default=None,
                        help="Layrd backend URL (overrides saved config)")
    parser.add_argument("--api-key", default=None, help="API key for authentication")
    parser.add_argument("--retry-failed", action="store_true",
                        help="Reset all failed uploads and retry them")
    parser.add_argument("--poll-interval", type=int, default=DEFAULT_POLL_INTERVAL,
                        help=f"Seconds between scans (default: {DEFAULT_POLL_INTERVAL})")

    args = parser.parse_args()
    setup_logging(args.verbose)

    db = Database()
    logger.info("Database at %s", db.db_path)

    if args.settings_only:
        completed = _run_setup(db)
        db.close()
        sys.exit(0 if completed else 1)

    # CLI folder management
    if args.add_folder:
        path, label = args.add_folder
        folder = db.add_folder(path, label, args.poll_interval)
        logger.info("Added watched folder: %s (%s)", folder.path, folder.label)
        print(f"Added: {folder.label} → {folder.path} (poll every {folder.poll_interval_seconds}s)")
        db.set_config("setup_complete", "true")
        db.close()
        return

    # Retry failed uploads
    if args.retry_failed:
        api_url = args.api_url or db.get_config("api_url", "http://localhost:8000")
        api_key = args.api_key or db.get_config("api_key")
        location = db.get_config("location", "")
        uploader = Uploader(base_url=api_url, api_key=api_key, location=location)
        engine = SyncEngine(db=db, uploader=uploader)
        count = engine.retry_failed()
        stats = db.get_upload_stats()
        print(f"Retried {count} file(s). Current stats: {stats}")
        uploader.close()
        db.close()
        return

    # First-run setup wizard
    if args.setup or _needs_setup(db):
        logger.info("Launching setup wizard")
        if not _run_setup(db):
            logger.info("Setup cancelled, exiting")
            db.close()
            return

    # Resolve API URL: CLI arg > saved config > default
    api_url = args.api_url or db.get_config("api_url", "http://localhost:8000")
    api_key = args.api_key or db.get_config("api_key")

    # Check for remote config override (server can redirect agents to a new URL)
    api_url, api_key = _fetch_remote_config(db, api_url, api_key)

    heartbeat, log_handler = _setup_heartbeat(db, api_url, api_key)

    location = db.get_config("location", "")
    uploader = Uploader(base_url=api_url, api_key=api_key, location=location)
    engine = SyncEngine(db=db, uploader=uploader)
    updater = Updater()

    # Wire heartbeat status and command handlers
    def _get_status():
        stats = db.get_upload_stats()
        folders = db.get_folders(enabled_only=False)
        return {
            "sync_status": "paused" if engine.paused else "active",
            "upload_stats": stats,
            "watched_folders": [
                {"path": f.path, "label": f.label, "enabled": f.enabled}
                for f in folders
            ],
            "last_reconcile": engine.last_reconcile,
            "poll_interval": args.poll_interval,
        }

    def _handle_command(command: str, params: dict | None):
        if command == "pause":
            engine.pause()
        elif command == "resume":
            engine.resume()
        elif command == "retry":
            engine.retry_failed()
        elif command == "set_config":
            if params:
                for key, value in params.items():
                    db.set_config(key, str(value))
                    logger.info("Remote config set: %s = %s", key, value)
        else:
            logger.warning("Unknown command: %s", command)

    heartbeat.get_status = _get_status
    heartbeat.on_command = _handle_command

    folders = db.get_folders(enabled_only=True)
    if not folders:
        logger.warning("No watched folders configured.")
        if not _run_setup(db):
            db.close()
            return
        folders = db.get_folders(enabled_only=True)
        if not folders:
            logger.error("Still no folders configured, exiting")
            db.close()
            return

    for f in folders:
        logger.info("Watching: %s → %s (every %ds)", f.label, f.path, f.poll_interval_seconds)

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        engine.run_sync_cycle,
        "interval",
        seconds=args.poll_interval,
        id="sync_cycle",
        max_instances=1,
    )
    scheduler.add_job(
        heartbeat.send_heartbeat,
        "interval",
        seconds=30,
        id="heartbeat",
        max_instances=1,
    )
    scheduler.add_job(
        lambda: _check_and_apply_update(updater),
        "interval",
        seconds=DEFAULT_UPDATE_CHECK_INTERVAL,
        id="update_check",
    )
    scheduler.start()
    logger.info("Scheduler started (poll every %ds)", args.poll_interval)

    engine.run_sync_cycle()
    heartbeat.send_heartbeat()

    if args.headless:
        logger.info("Running in headless mode. Ctrl+C to stop.")
        try:
            signal.pause() if hasattr(signal, "pause") else _wait_forever()
        except KeyboardInterrupt:
            pass
    else:
        tray = TrayApp(db=db, sync_engine=engine, updater=updater)

        def on_scan_done(uploaded, failed):
            status = f"Last sync: {uploaded} uploaded"
            if failed:
                status += f", {failed} failed"
            tray.update_status(status)

        engine.on_scan_complete.append(on_scan_done)
        tray.run()

    logger.info("Shutting down...")
    scheduler.shutdown(wait=False)
    heartbeat.send_heartbeat()  # final heartbeat
    uploader.close()
    updater.close()
    heartbeat.close()
    db.close()


def _check_and_apply_update(updater: Updater):
    """Check for updates and auto-apply if available."""
    info = updater.check_for_update()
    if info:
        logger.info("Downloading update v%s...", info.get("version"))
        if updater.download_and_apply(info):
            logger.info("Update applied, exiting for restart")
            sys.exit(0)


def _wait_forever():
    """Fallback for platforms without signal.pause()."""
    import time
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
