import os

import requests
from flask import Flask, request, jsonify

import llm01
import llm02
import llm07
import llm09
import llm10

app = Flask(__name__)

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434")
MODEL = os.environ.get("MODEL", "llama3.2:3b")

MODULES = {
    "llm01": llm01,
    "llm02": llm02,
    "llm07": llm07,
    "llm09": llm09,
    "llm10": llm10,
}

DEFAULT_TIMEOUT = 120


def call_ollama(system_prompt: str, user_message: str, max_tokens: int = None, timeout: int = DEFAULT_TIMEOUT) -> str:
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "stream": False,
    }
    if max_tokens:
        payload["options"] = {"num_predict": max_tokens}
    try:
        r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=timeout)
        r.raise_for_status()
        return r.json()["message"]["content"]
    except requests.exceptions.ConnectionError:
        return "ERROR: Cannot reach Ollama. Is it running?"
    except requests.exceptions.Timeout:
        return "ERROR: Request to Ollama timed out."
    except Exception:
        app.logger.exception("call_ollama failed")
        return "ERROR: the model backend is temporarily unreachable."


@app.route("/<challenge_id>/chat", methods=["POST"])
def chat(challenge_id):
    module = MODULES.get(challenge_id)
    if not module:
        return jsonify({"error": "Challenge not found"}), 404

    data = request.get_json(force=True)
    user_message = (data.get("message") or "").strip()
    if not user_message:
        return jsonify({"error": "message field required"}), 400

    challenge = module.CHALLENGE
    max_tokens = getattr(module, "MAX_TOKENS", None)
    timeout = getattr(module, "REQUEST_TIMEOUT", DEFAULT_TIMEOUT)

    response = call_ollama(challenge["system_prompt"], user_message, max_tokens=max_tokens, timeout=timeout)
    solved = module.check_flag(user_message, response)

    return jsonify({
        "response": response,
        "solved": solved,
        "flag": challenge["flag"] if solved else None,
        "points": challenge["points"] if solved else 0,
    })


@app.route("/<challenge_id>/meta")
def meta(challenge_id):
    module = MODULES.get(challenge_id)
    if not module:
        return jsonify({"error": "Challenge not found"}), 404
    c = module.CHALLENGE
    return jsonify({k: c[k] for k in ("id", "name", "points", "description", "hint")})


@app.route("/health")
def health():
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        ollama_ok = r.status_code == 200
    except Exception:
        ollama_ok = False
    return jsonify({
        "status": "ok",
        "ollama": "connected" if ollama_ok else "unreachable",
        "challenges": list(MODULES.keys()),
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
