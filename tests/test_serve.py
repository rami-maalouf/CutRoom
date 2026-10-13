# `cutroom review --serve`: the review page and its media over the local network

import json
import re
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from cutroom import serve as served
from cutroom.cli import main
from conftest import needs_ffmpeg
from test_workflow import talk, write_project  # noqa: F401 (fixture)


def test_byte_ranges_follow_the_http_rules():
    assert served.parse_range(None, 100) is None
    assert served.parse_range("bytes=0-", 100) == (0, 99)
    assert served.parse_range("bytes=10-19", 100) == (10, 19)
    assert served.parse_range("bytes=90-500", 100) == (90, 99)
    assert served.parse_range("bytes=-10", 100) == (90, 99)
    assert served.parse_range("bytes=0-1,5-6", 100) is None  # multiple ranges: send the whole file
    for bad in ("bytes=100-", "bytes=20-10", "bytes=x-", "bytes=-0"):
        with pytest.raises(ValueError):
            served.parse_range(bad, 100)


@pytest.fixture
def server(talk, monkeypatch):  # noqa: F811
    write_project(talk, shorts=[{"id": "S1", "start": 3.5, "end": 11.5, "title": "the point", "why": "standalone"}])
    captured = {}
    monkeypatch.setattr(served, "serve", lambda plan_job, port: captured.update(plan_job=plan_job))
    main(["review", str(talk), "--serve"])
    review = served.Review(captured["plan_job"], "tok")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), served.handler(review))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", talk
    httpd.shutdown()
    httpd.server_close()


def get(url, **headers):
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers)) as r:
        return r.status, dict(r.headers), r.read()


def page_data(body):
    return json.loads(re.search(rb'<script type="application/json" id="data">(.*?)</script>', body, re.S).group(1))


@needs_ffmpeg
def test_the_served_page_plays_media_over_the_network(server):
    base, talk = server
    status, _, body = get(f"{base}/tok/")
    data = page_data(body)
    assert status == 200 and data["served"] is True
    assert data["media"][0]["uri"] == "media/0/talk.mp4"  # relative to the page, never a file:// path

    size = talk.stat().st_size
    status, headers, chunk = get(f"{base}/tok/media/0/talk.mp4", Range="bytes=10-19")
    assert status == 206 and chunk == talk.read_bytes()[10:20]
    assert headers["Content-Range"] == f"bytes 10-19/{size}" and headers["Accept-Ranges"] == "bytes"
    status, headers, whole = get(f"{base}/tok/media/0/talk.mp4")
    assert status == 200 and len(whole) == size and headers["Content-Type"] == "video/mp4"

    for path, code in (("/wrong/", 404), ("/tok/media/1/x.mp4", 404), ("/tok/../talk.mp4", 404)):
        with pytest.raises(urllib.error.HTTPError) as err:
            get(base + path)
        assert err.value.code == code
    with pytest.raises(urllib.error.HTTPError) as err:
        get(f"{base}/tok/media/0/talk.mp4", Range=f"bytes={size}-")
    assert err.value.code == 416


@needs_ffmpeg
def test_a_project_edit_shows_on_reload_and_feedback_is_saved(server):
    base, talk = server
    assert [s["id"] for s in page_data(get(f"{base}/tok/")[2])["shorts"]] == ["S1"]
    write_project(talk, shorts=[])
    assert page_data(get(f"{base}/tok/")[2])["shorts"] == []

    text = "Export S1:\n  cutroom export talk.mp4 S1"
    req = urllib.request.Request(f"{base}/tok/feedback", data=text.encode(), method="POST")
    with urllib.request.urlopen(req) as r:
        assert r.status == 200
    saved = talk.with_suffix(".feedback.md").read_text(encoding="utf-8")
    assert saved.startswith("# review feedback (") and saved.endswith(text + "\n")
