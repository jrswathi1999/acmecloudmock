"""The build network's egress proxy: blocks and logs every outbound attempt.

CI starts it automatically for each run (tagging attempts with the run id).
You can also run it standalone:  python -m ops.egress_proxy
The allowlist is empty, so nothing is ever forwarded.
"""
import os
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from ops import common

ALLOWLIST = set()  # hosts allowed out. Empty on purpose.
RUN_FILE = common.PROD / "ci_current_run"


class _ProxyServer(ThreadingHTTPServer):
    daemon_threads = True
    # On Windows SO_REUSEADDR lets two servers share a port; we want a clean "port in use" error.
    allow_reuse_address = os.name != "nt"

    def __init__(self, run_id=None):
        super().__init__(("127.0.0.1", common.PROXY_PORT), _Handler)
        self.run_id = run_id
        self.attempts = []

    def current_run(self):
        if self.run_id is not None:
            return self.run_id
        try:
            return int(common.read_text(RUN_FILE).strip())
        except (OSError, ValueError):
            return None


class _Handler(BaseHTTPRequestHandler):
    server_version = "acme-egress/1.0"
    protocol_version = "HTTP/1.1"

    def _block(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length > 0 else b""
        if self.command == "CONNECT":
            host = self.path.rsplit(":", 1)[0]
        else:
            host = urlsplit(self.path).hostname or (self.headers.get("Host") or "").split(":")[0]
        record = common.log(
            "egress",
            source="ci-runner",
            run=self.server.current_run(),
            method=self.command,
            host=host,
            bytes_out=len(body),
            allowed=host in ALLOWLIST,
        )
        self.server.attempts.append(record)
        msg = b"403 blocked by acme egress policy (allowlist is empty)\n"
        self.send_response(403)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(msg)))
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(msg)
        self.close_connection = True

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = do_CONNECT = _block

    def log_message(self, *args):  # keep the console quiet; the egress log is the record
        pass


@contextmanager
def running(run_id: int):
    """Run the proxy for the duration of one CI run. Yields the list of blocked attempts."""
    try:
        server = _ProxyServer(run_id)
    except OSError:
        # A standalone proxy already owns the port: tell it which run is active.
        common.write_text(RUN_FILE, str(run_id))
        try:
            yield []
        finally:
            try:
                RUN_FILE.unlink()
            except OSError:
                pass
        return
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True)
    thread.start()
    try:
        yield server.attempts
    finally:
        server.shutdown()
        server.server_close()


def main() -> None:
    server = _ProxyServer()
    common.say(f"egress proxy on {common.PROXY_URL}: blocking and logging everything to {common.LOGS / 'egress.jsonl'}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
