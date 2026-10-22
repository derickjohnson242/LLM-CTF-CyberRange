import os
import threading
import time
from urllib.parse import urlsplit

from flask import Flask, request, Response, jsonify
from playwright.sync_api import sync_playwright

app = Flask(__name__)

CALLBACK_HOST = os.environ.get("CALLBACK_HOST", "llm05-app")
LOCAL_HOSTS = {"localhost", "127.0.0.1"}

_render_store = {}
_lock = threading.Lock()

ATTEMPT_TTL = 600
MAX_ATTEMPTS = 500


def _sweep_expired() -> None:
    """Call with _lock held."""
    now = time.time()
    expired = [aid for aid, e in _render_store.items() if now - e["created"] > ATTEMPT_TTL]
    for aid in expired:
        del _render_store[aid]
    if len(_render_store) > MAX_ATTEMPTS:
        oldest = sorted(_render_store.items(), key=lambda kv: kv[1]["created"])
        for aid, _ in oldest[: len(_render_store) - MAX_ATTEMPTS]:
            del _render_store[aid]


MAX_CONCURRENT_VISITS = int(os.environ.get("MAX_CONCURRENT_VISITS", "2"))
_visit_semaphore = threading.Semaphore(MAX_CONCURRENT_VISITS)

COMMENT_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Comment Preview</title></head>
<body>
<h3>Latest comment</h3>
<div class="comment-body">{content}</div>
</body></html>"""


@app.route("/render/<attempt_id>")
def render(attempt_id):
    with _lock:
        entry = _render_store.get(attempt_id)
    if not entry:
        return Response("not found", status=404)

    resp = Response(COMMENT_PAGE.format(content=entry["html"]), mimetype="text/html")
    resp.set_cookie(
        "ctf_flag_cookie",
        entry["canary"],
        httponly=False,
        samesite="Lax",
    )
    return resp


@app.route("/visit", methods=["POST"])
def visit():
    """Called by the llm05 app container after each turn: stash the rendered
    HTML, then have a headless browser actually visit it, simulating a victim."""
    data = request.get_json(force=True)
    attempt_id = data["attempt_id"]
    html = data["html"]
    canary = data["canary"]

    with _lock:
        _sweep_expired()
        _render_store[attempt_id] = {"html": html, "canary": canary, "created": time.time()}

    if not _visit_semaphore.acquire(blocking=False):
        return jsonify({"error": "too many concurrent visits, try again shortly"}), 429

    def run_and_release():
        try:
            _headless_visit(attempt_id)
        finally:
            _visit_semaphore.release()

    threading.Thread(target=run_and_release, daemon=True).start()
    return jsonify({"status": "queued"})


def _headless_visit(attempt_id: str):
    url = f"http://localhost:5010/render/{attempt_id}"
    try:
        with sync_playwright() as p:
            # --no-sandbox is required because the container drops all capabilities; isolation comes from render_net.
            browser = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
            context = browser.new_context()

            def route_handler(route):
                parsed = urlsplit(route.request.url)
                host = parsed.hostname or ""
                # The page may only reload its own render, never call /visit to spawn more browsers.
                if host in LOCAL_HOSTS:
                    if route.request.method == "GET" and parsed.path.startswith("/render/"):
                        route.continue_()
                    else:
                        route.abort()
                elif host == CALLBACK_HOST:
                    route.continue_()
                else:
                    route.abort()

            context.route("**/*", route_handler)
            page = context.new_page()
            page.goto(url, timeout=10000)
            page.wait_for_timeout(3000)
            browser.close()
    except Exception as e:
        print(f"[renderer] visit error for {attempt_id}: {e}")


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5010)
