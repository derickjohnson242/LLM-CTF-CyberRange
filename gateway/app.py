import hmac
import os
import secrets
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from functools import wraps

import requests
from flask import Flask, request, jsonify, render_template, redirect, url_for, Response, session

app = Flask(__name__)

# Signs session cookies. If unset, a random key is used and sessions reset on restart.
SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    SECRET_KEY = secrets.token_hex(32)
    print("[gateway] WARNING: SECRET_KEY not set, generated a random one at "
          "startup. Sessions will not survive a gateway restart. Set "
          "SECRET_KEY in the environment for a stable key.")
app.secret_key = SECRET_KEY

CLASS_PASSCODE = os.environ.get("CLASS_PASSCODE", "changeme-passcode")

_GROUP_A = "http://group-a:5000"
CHALLENGE_UPSTREAM = {
    "llm01": f"{_GROUP_A}/llm01",
    "llm02": f"{_GROUP_A}/llm02",
    "llm03": "http://llm03:5003",
    "llm04": "http://llm04:5004",
    "llm05": "http://llm05:5005",
    "llm06": "http://llm06:5006",
    "llm07": f"{_GROUP_A}/llm07",
    "llm08": "http://llm08:5008",
    "llm09": f"{_GROUP_A}/llm09",
    "llm10": f"{_GROUP_A}/llm10",
}


# Challenge text comes from each container's /meta, so it can't drift from the real challenge.
META_CACHE_TTL = 60
_meta_cache = {}
_meta_lock = threading.Lock()


def _fetch_meta(challenge_id: str, upstream: str) -> dict:
    try:
        r = requests.get(f"{upstream}/meta", timeout=3)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException:
        return {
            "id": challenge_id,
            "name": f"{challenge_id.upper()} (offline)",
            "points": 0,
            "description": "This challenge container is temporarily unreachable. Try again shortly.",
            "hint": "",
            "offline": True,
        }


def get_challenge_meta(challenge_id: str) -> dict:
    upstream = CHALLENGE_UPSTREAM.get(challenge_id)
    if not upstream:
        return None
    now = time.time()
    with _meta_lock:
        cached = _meta_cache.get(challenge_id)
    if cached and cached[0] > now:
        return cached[1]

    meta = _fetch_meta(challenge_id, upstream)
    if not meta.get("offline"):
        with _meta_lock:
            _meta_cache[challenge_id] = (now + META_CACHE_TTL, meta)
    return meta


def get_all_challenge_meta() -> dict:
    return {cid: get_challenge_meta(cid) for cid in CHALLENGE_UPSTREAM}


# Failed logins are throttled per IP: an attacker guessing the passcode has no session yet.
LOGIN_ATTEMPT_WINDOW = 60
LOGIN_ATTEMPT_MAX = 5
_login_attempts = {}
_login_lock = threading.Lock()


def _client_ip() -> str:
    return request.remote_addr or "unknown"


def _login_rate_limited(ip: str) -> bool:
    now = time.time()
    with _login_lock:
        attempts = [t for t in _login_attempts.get(ip, []) if now - t < LOGIN_ATTEMPT_WINDOW]
        if attempts:
            _login_attempts[ip] = attempts
        else:
            _login_attempts.pop(ip, None)
        return len(attempts) >= LOGIN_ATTEMPT_MAX


def _record_login_failure(ip: str) -> None:
    with _login_lock:
        _login_attempts.setdefault(ip, []).append(time.time())


# Per-session limits on model calls, so one student can't starve the shared Ollama backend.
RATE_LIMIT_PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "10"))
RATE_LIMIT_CONCURRENT = int(os.environ.get("RATE_LIMIT_CONCURRENT", "1"))

_rl_history = defaultdict(list)
_rl_inflight = defaultdict(int)
_rl_lock = threading.Lock()


def _session_sid() -> str:
    sid = session.get("sid")
    if not sid:
        sid = secrets.token_hex(16)
        session["sid"] = sid
    return sid


class RateLimited(Exception):
    def __init__(self, message):
        self.message = message


@contextmanager
def _rate_limited_call():
    sid = _session_sid()
    now = time.time()
    with _rl_lock:
        hist = [t for t in _rl_history[sid] if now - t < 60]
        if len(hist) >= RATE_LIMIT_PER_MINUTE:
            _rl_history[sid] = hist
            raise RateLimited(f"Rate limit: max {RATE_LIMIT_PER_MINUTE} requests per minute. Wait a bit and retry.")
        if _rl_inflight[sid] >= RATE_LIMIT_CONCURRENT:
            raise RateLimited(f"Rate limit: only {RATE_LIMIT_CONCURRENT} request(s) at a time per session.")
        hist.append(now)
        _rl_history[sid] = hist
        _rl_inflight[sid] += 1
    try:
        yield
    finally:
        with _rl_lock:
            _rl_inflight[sid] -= 1


def rate_limit_llm(fn):
    """Apply to routes that trigger an Ollama call (directly or via a
    challenge container), not to cheap proxy routes like /status or /reset."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            with _rate_limited_call():
                return fn(*args, **kwargs)
        except RateLimited as e:
            return jsonify({"error": e.message}), 429
    return wrapper


def require_auth_page(fn):
    """Redirects to /login. Use for browser-facing HTML routes."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


def require_auth_api(fn):
    """Returns 401 JSON. Use for API/chat routes called by the page's JS."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("authenticated"):
            return jsonify({"error": "Not authenticated"}), 401
        return fn(*args, **kwargs)
    return wrapper


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        ip = _client_ip()
        if _login_rate_limited(ip):
            error = "Too many incorrect attempts. Wait a minute and try again."
        else:
            handle = (request.form.get("handle") or "").strip()
            passcode = request.form.get("passcode", "")
            if not handle:
                error = "Enter a handle."
            elif not hmac.compare_digest(passcode, CLASS_PASSCODE):
                _record_login_failure(ip)
                error = "Incorrect passcode."
            else:
                # Start from a clean session on login to prevent session fixation.
                session.clear()
                session["authenticated"] = True
                session["student"] = handle[:60]
                return redirect(url_for("index"))
    return render_template("login.html", error=error)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@require_auth_page
def index():
    return render_template(
        "index.html",
        challenges=get_all_challenge_meta(),
        student=session.get("student", ""),
    )


@app.route("/api/challenges", methods=["GET"])
@require_auth_api
def list_challenges():
    return jsonify(list(get_all_challenge_meta().values()))


@app.route("/api/challenge/<challenge_id>", methods=["GET"])
@require_auth_api
def get_challenge(challenge_id):
    meta = get_challenge_meta(challenge_id)
    if not meta:
        return jsonify({"error": "Challenge not found"}), 404
    return jsonify(meta)


@app.route("/challenge/<challenge_id>/chat", methods=["POST"])
@require_auth_api
@rate_limit_llm
def chat(challenge_id):
    upstream = CHALLENGE_UPSTREAM.get(challenge_id)
    if not upstream:
        return jsonify({"error": "Challenge not found"}), 404

    data = request.get_json(force=True)
    user_message = (data.get("message") or "").strip()
    # Identity always comes from the session, never from the request body.
    student_name = session.get("student", "anonymous")

    if not user_message:
        return jsonify({"error": "message field required"}), 400

    try:
        r = requests.post(
            f"{upstream}/chat",
            json={"message": user_message, "student": student_name},
            timeout=125,
        )
        r.raise_for_status()
        result = r.json()
    except requests.exceptions.RequestException:
        app.logger.exception("chat: upstream %s unreachable", challenge_id)
        return jsonify({"error": "This challenge is temporarily unreachable."}), 502

    solved = bool(result.get("solved"))
    resp = {
        "response": result.get("response", ""),
        "solved": solved,
        "flag": result.get("flag") if solved else None,
        "points": result.get("points", 0) if solved else 0,
    }
    for k in ("attempt_id", "preview_url"):
        if k in result:
            resp[k] = result[k]
    return jsonify(resp)


@app.route("/challenge/llm05/preview/<attempt_id>", methods=["GET"])
@require_auth_api
def llm05_preview(attempt_id):
    upstream = CHALLENGE_UPSTREAM["llm05"]
    try:
        r = requests.get(f"{upstream}/preview/{attempt_id}", timeout=5)
    except requests.exceptions.RequestException:
        app.logger.exception("llm05_preview: upstream unreachable")
        return jsonify({"error": "This challenge is temporarily unreachable."}), 502
    resp = Response(r.content, status=r.status_code, mimetype="text/html")
    # Model-generated HTML: keep it sandboxed even if the URL is opened directly in a tab.
    resp.headers["Content-Security-Policy"] = "sandbox allow-scripts"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/challenge/llm05/status/<attempt_id>", methods=["GET"])
@require_auth_api
def llm05_status(attempt_id):
    upstream = CHALLENGE_UPSTREAM["llm05"]
    try:
        r = requests.get(f"{upstream}/status/{attempt_id}", timeout=5)
    except requests.exceptions.RequestException:
        app.logger.exception("llm05_status: upstream unreachable")
        return jsonify({"error": "This challenge is temporarily unreachable."}), 502
    return Response(r.content, status=r.status_code, mimetype="application/json")


def _proxy_challenge(challenge_id: str, path: str, body: dict):
    try:
        r = requests.post(f"{CHALLENGE_UPSTREAM[challenge_id]}/{path}", json=body, timeout=130)
    except requests.exceptions.RequestException:
        app.logger.exception("_proxy_challenge: %s/%s unreachable", challenge_id, path)
        return jsonify({"error": "This challenge is temporarily unreachable."}), 502
    return Response(r.content, status=r.status_code, mimetype="application/json")


@app.route("/challenge/llm08/insert", methods=["POST"])
@require_auth_api
@rate_limit_llm
def llm08_insert():
    data = request.get_json(force=True)
    return _proxy_challenge("llm08", "insert", {
        "student": session.get("student", "anonymous"),
        "title": data.get("title") or "",
        "text": data.get("text") or "",
    })


@app.route("/challenge/llm08/verify", methods=["POST"])
@require_auth_api
@rate_limit_llm
def llm08_verify():
    return _proxy_challenge("llm08", "verify", {"student": session.get("student", "anonymous")})


@app.route("/challenge/llm08/reset", methods=["POST"])
@require_auth_api
def llm08_reset():
    return _proxy_challenge("llm08", "reset", {"student": session.get("student", "anonymous")})


@app.route("/challenge/llm04/insert", methods=["POST"])
@require_auth_api
@rate_limit_llm
def llm04_insert():
    data = request.get_json(force=True)
    return _proxy_challenge("llm04", "insert", {
        "student": session.get("student", "anonymous"),
        "question": data.get("question") or "",
        "answer": data.get("answer") or "",
    })


@app.route("/challenge/llm04/verify", methods=["POST"])
@require_auth_api
@rate_limit_llm
def llm04_verify():
    return _proxy_challenge("llm04", "verify", {"student": session.get("student", "anonymous")})


@app.route("/challenge/llm04/reset", methods=["POST"])
@require_auth_api
def llm04_reset():
    return _proxy_challenge("llm04", "reset", {"student": session.get("student", "anonymous")})


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "challenges_registered": len(CHALLENGE_UPSTREAM),
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False, threaded=True)
