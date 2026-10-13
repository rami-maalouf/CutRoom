# `cutroom review --serve`: the review page for a phone. the page on disk plays
# file:// paths, which only this computer can open, so this serves the page and
# the project's own media files over the local network instead.
#
# - every url starts with a random token, so other devices on the network
#   cannot guess it; only the job's media files are reachable, by index.
# - media answers byte ranges: phones play and seek video through them.
# - the page is re-planned when the project file or the story changes, so a
#   reload on the phone shows the agent's latest edit.
# - "Send to agent" posts the feedback text, written to feedback_path(job).

import mimetypes
import secrets
import socket
import sys
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from .review import feedback_path, review_html
from .script import story_path
from . import project

CHUNK = 1 << 20
MAX_FEEDBACK = 1 << 20


def lan_address() -> str:
    # the address other devices reach this computer on; connecting a udp
    # socket sends nothing, it only picks the outgoing interface
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    # "bytes=a-b", "bytes=a-" or "bytes=-n" -> inclusive (start, end); None = whole file
    if not header or not header.startswith("bytes=") or "," in header:
        return None
    first, _, last = header[6:].strip().partition("-")
    try:
        if first == "":
            n = int(last)
            if n <= 0:
                raise ValueError
            return max(0, size - n), size - 1
        start = int(first)
        end = int(last) if last else size - 1
    except ValueError:
        raise ValueError(header) from None
    if start >= size or end < start:
        raise ValueError(header)
    return start, min(end, size - 1)


class Review:
    # the job behind the page, re-planned when its inputs change
    def __init__(self, plan_job, token: str):
        self.plan_job, self.token = plan_job, token
        self.lock = threading.Lock()
        self.job = plan_job()
        self.stamp = self.inputs()
        self.html = self.build()

    def inputs(self) -> tuple:
        files = [project.project_path(self.job.src), story_path(self.job)]
        return tuple(f.stat().st_mtime_ns if f.exists() else 0 for f in files)

    def build(self) -> bytes:
        return review_html(self.job, media_uri=lambda i, path: f"media/{i}/{path.name}", served=True).encode()

    def page(self) -> bytes:
        with self.lock:
            stamp = self.inputs()
            if stamp != self.stamp:
                print("project changed: re-planning the review page ...", flush=True)
                self.job = self.plan_job()
                self.stamp, self.html = stamp, self.build()
            return self.html

    def media(self, i: int) -> Path | None:
        sessions = self.job.sessions
        return sessions[i]["path"] if 0 <= i < len(sessions) else None


def handler(review: Review):
    prefix = f"/{review.token}/"

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def handle(self):
            # phones drop connections all the time (a seek cancels the last
            # range request): that is normal, not an error worth a traceback
            try:
                super().handle()
            except (ConnectionError, TimeoutError):
                pass

        def route(self) -> str | None:
            path = unquote(self.path.split("?", 1)[0])
            if path == prefix.rstrip("/"):
                return ""
            return path[len(prefix):] if path.startswith(prefix) else None

        def reply(self, code: int, body: bytes = b"", kind: str = "text/plain; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            route = self.route()
            if route is None:
                return self.reply(404, b"not found")
            if route == "" and not self.path.split("?", 1)[0].endswith("/"):
                self.send_response(301)
                self.send_header("Location", prefix)
                self.send_header("Content-Length", "0")
                return self.end_headers()
            if route == "":
                return self.reply(200, review.page(), "text/html; charset=utf-8")
            parts = route.split("/")
            if len(parts) >= 2 and parts[0] == "media" and parts[1].isdigit():
                return self.send_media(review.media(int(parts[1])))
            self.reply(404, b"not found")

        def send_media(self, path: Path | None):
            if path is None or not path.is_file():
                return self.reply(404, b"no such media")
            size = path.stat().st_size
            try:
                span = parse_range(self.headers.get("Range"), size)
            except ValueError:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                return self.end_headers()
            start, end = span or (0, size - 1)
            self.send_response(206 if span else 200)
            self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            if span:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            if self.command == "HEAD":
                return
            try:
                with path.open("rb") as f:
                    f.seek(start)
                    left = end - start + 1
                    while left > 0:
                        chunk = f.read(min(CHUNK, left))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        left -= len(chunk)
            except ConnectionError:
                pass  # the player moved on: browsers drop range requests all the time

        def do_POST(self):
            if self.route() != "feedback":
                return self.reply(404, b"not found")
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 < length <= MAX_FEEDBACK:
                return self.reply(400, b"empty or too large")
            text = self.rfile.read(length).decode("utf-8", "replace").strip()
            dst = feedback_path(review.job)
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            dst.write_text(f"# review feedback ({stamp})\n\n{text}\n", encoding="utf-8")
            print(f"\nfeedback from the review page -> {dst}\n{text}\n", flush=True)
            self.reply(200, str(dst).encode())

    return Handler


def show_qr(url: str) -> None:
    try:
        import segno
    except ImportError:
        return
    segno.make(url, error="m").terminal(compact=True)


def serve(plan_job, port: int) -> None:
    # plan_job() -> Job; blocks until ctrl-c
    review = Review(plan_job, secrets.token_urlsafe(12))
    try:
        server = ThreadingHTTPServer(("0.0.0.0", port), handler(review))
    except OSError:
        server = ThreadingHTTPServer(("0.0.0.0", 0), handler(review))  # the port is taken: any free one
    server.daemon_threads = True
    port = server.server_address[1]
    url = f"http://{lan_address()}:{port}/{review.token}/"
    print(f"\nreview page for your phone (same wi-fi): {url}")
    print(f"on this computer: http://localhost:{port}/{review.token}/")
    show_qr(url)
    print("reload the page after an edit; ctrl-c stops the server", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped", file=sys.stderr)
    finally:
        server.server_close()
