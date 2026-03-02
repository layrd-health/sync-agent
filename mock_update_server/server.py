"""Mock server for testing OTA updates and remote logging.

Usage:
    # Serve version 0.2.0 (for OTA update testing):
    uv run python -m mock_update_server.server --version 0.2.0 --exe-path dist/LayrdSync.exe

    # Just run the log receiver (no update):
    uv run python -m mock_update_server.server --version 0.1.0

Endpoints:
    GET  /api/sync-agent/version  — version info for OTA
    GET  /download/LayrdSync.exe  — binary download
    POST /api/sync-agent/logs     — receive log batches
"""

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler


class MockHandler(SimpleHTTPRequestHandler):
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

    def do_POST(self):
        if self.path == "/api/sync-agent/logs":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                payload = json.loads(body)
                agent_id = payload.get("agent_id", "?")[:8]
                hostname = payload.get("hostname", "?")
                version = payload.get("agent_version", "?")
                records = payload.get("records", [])

                print(f"\n{'='*60}")
                print(f"  Logs from {hostname} (agent={agent_id}..., v{version})")
                print(f"  {len(records)} record(s) at {datetime.now().strftime('%H:%M:%S')}")
                print(f"{'='*60}")
                for r in records:
                    ts = r.get("ts", "")
                    ts_short = ts[11:19] if len(ts) > 19 else ts
                    level = r.get("level", "?")
                    msg = r.get("message", "")
                    exc = r.get("exc")
                    marker = {"ERROR": "!!", "WARNING": "! ", "INFO": "  ", "DEBUG": "  "}.get(level, "  ")
                    print(f"  {marker} [{ts_short}] {level:7s} {msg}")
                    if exc:
                        for line in exc.strip().splitlines():
                            print(f"     {line}")
                print()

            except json.JSONDecodeError:
                print(f"  [bad json] {body[:200]}")

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, fmt, *args):
        pass  # suppress default access logs


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description="Mock OTA + log server")
    parser.add_argument("--version", required=True, help="Version to advertise (e.g. 0.2.0)")
    parser.add_argument("--exe-path", default=None, help="Path to .exe to serve for download")
    parser.add_argument("--port", type=int, default=9090, help="Port (default: 9090)")
    args = parser.parse_args()

    exe_path = Path(args.exe_path) if args.exe_path else None
    sha256 = compute_sha256(exe_path) if exe_path and exe_path.exists() else None

    version_info = {
        "version": args.version,
        "download_url": f"http://localhost:{args.port}/download/LayrdSync.exe",
    }
    if sha256:
        version_info["sha256"] = sha256

    MockHandler.version_info = version_info
    MockHandler.exe_path = exe_path

    print(f"Mock server on port {args.port}")
    print(f"  OTA version: {args.version}")
    print(f"  Log endpoint: POST /api/sync-agent/logs")
    if sha256:
        print(f"  SHA-256: {sha256}")
    print()

    server = HTTPServer(("0.0.0.0", args.port), MockHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down")
        server.shutdown()


if __name__ == "__main__":
    main()
