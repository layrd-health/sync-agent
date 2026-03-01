"""Mock OTA update server for testing the self-updater.

Usage:
    # Serve version 0.2.0 with the given exe file:
    uv run python -m mock_update_server.server --version 0.2.0 --exe-path dist/LayrdSync.exe

    # Or just serve version info without an actual binary:
    uv run python -m mock_update_server.server --version 0.2.0

The agent checks GET /api/sync-agent/version and downloads from the returned URL.
"""

import argparse
import hashlib
import json
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler


class UpdateHandler(SimpleHTTPRequestHandler):
    version_info: dict = {}
    exe_path: Path | None = None

    def do_GET(self):
        if self.path == "/api/sync-agent/version":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(self.version_info).encode())
            return

        if self.path == "/download/LayrdSync.exe" and self.exe_path and self.exe_path.exists():
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(self.exe_path.stat().st_size))
            self.end_headers()
            with open(self.exe_path, "rb") as f:
                while chunk := f.read(8192):
                    self.wfile.write(chunk)
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        print(f"[mock-update-server] {args[0]}")


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description="Mock OTA update server")
    parser.add_argument("--version", required=True, help="Version to advertise (e.g. 0.2.0)")
    parser.add_argument("--exe-path", default=None, help="Path to the .exe to serve for download")
    parser.add_argument("--port", type=int, default=9090, help="Port to serve on (default: 9090)")
    args = parser.parse_args()

    exe_path = Path(args.exe_path) if args.exe_path else None
    sha256 = compute_sha256(exe_path) if exe_path and exe_path.exists() else None

    version_info = {
        "version": args.version,
        "download_url": f"http://localhost:{args.port}/download/LayrdSync.exe",
    }
    if sha256:
        version_info["sha256"] = sha256

    UpdateHandler.version_info = version_info
    UpdateHandler.exe_path = exe_path

    print(f"Mock update server starting on port {args.port}")
    print(f"  Version: {args.version}")
    print(f"  Download URL: {version_info['download_url']}")
    if sha256:
        print(f"  SHA-256: {sha256}")
    else:
        print("  No exe file — version check only")
    print()

    server = HTTPServer(("0.0.0.0", args.port), UpdateHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down")
        server.shutdown()


if __name__ == "__main__":
    main()
