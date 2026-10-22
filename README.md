# OWASP LLM Top 10 — CTF Training Range

A self-hosted capture-the-flag range for teaching the
[OWASP Top 10 for LLM Applications](https://genai.owasp.org/llm-top-10/).
Ten deliberately vulnerable AI challenges, one per OWASP category, run against a
local **llama3.2:3b** model (via Ollama) inside Docker. An instructor starts it on
one machine. Students join from any browser on the same network.

No cloud services, API keys, or GPU needed.

> [!WARNING]
> **This software is intentionally vulnerable.** Run it on a trusted classroom or
> lab network only. Never expose port 8080 to the internet.
>
> **Flags and system prompts are in the source code.** If this repository is
> public, students can read the answers. Keep the repo private, or change the
> flags before class (see [Changing the flags](#changing-the-flags)).

---

## Contents

- [Challenges](#challenges)
- [Architecture](#architecture)
- [Requirements](#requirements)
- [Setup: Windows](#setup-windows)
- [Setup: Linux / macOS](#setup-linux--macos)
- [Check that it works](#check-that-it-works)
- [Running a class](#running-a-class)
- [Configuration](#configuration)
- [Project layout](#project-layout)
- [Useful commands](#useful-commands)
- [Troubleshooting](#troubleshooting)
- [Known limitations](#known-limitations)
- [Reference dataset](#reference-dataset)

---

## Challenges

| ID | Category | Points | What the student does | How the solve is verified |
|---|---|---|---|---|
| LLM01 | Prompt Injection | 100 | Make an assistant say a word it's forbidden to say | Word appears in the response |
| LLM02 | Sensitive Information Disclosure | 100 | Extract confidential HR data (salary, SSN, passphrase) from the context | Secret value appears in the response |
| LLM03 | Supply Chain | 150 | Trigger a poisoned third-party "plugin" so the assistant injects a backdoor into code it formats | Backdoor appears in formatted code. Asking the model to just repeat it doesn't count |
| LLM04 | Data & Model Poisoning | 150 | Submit poisoned training examples so the assistant gives dangerous security advice | A **different, fixed** question must produce the bad advice (proves it generalized) |
| LLM05 | Improper Output Handling | 150 | Get the model to emit HTML that steals a cookie | A **real headless browser** loads the output; the stolen cookie must reach a callback |
| LLM06 | Excessive Agency | 200 | Get an autonomous agent with real database tools to delete every user, directly or by planting an instruction it reads | The real database table is actually empty afterwards |
| LLM07 | System Prompt Leakage | 100 | Extract a secret from the system prompt | Secret appears in the response |
| LLM08 | Vector & Embedding Weaknesses | 200 | Submit a document to a live knowledge base that gets retrieved and hijacks the answer | Real embedding retrieval must pick your document for a fixed question, and the answer must contain the target code |
| LLM09 | Misinformation | 150 | Find the topic where the assistant confidently states false medical information | Response must assert the false claim (a correct debunk doesn't count) |
| LLM10 | Unbounded Consumption | 200 | Make the model produce runaway output | Response is 300+ words (generation is capped so one student can't hog the server) |

Each challenge shows the flag in the UI as soon as it's solved. Points are
informational only: there's no scoreboard, and nothing is saved between restarts.

---

## Architecture

```
Students (browsers on the LAN)
    │  HTTP :8080  — login with handle + class passcode
    ▼
gateway (Flask)        auth, rate limiting, UI, reverse proxy — holds no flags or prompts
    │
    ├─→ group-a          LLM01, 02, 07, 09, 10   (prompt-in / text-out, share one container)
    ├─→ llm03            Supply Chain
    ├─→ llm04            Data & Model Poisoning  (per-student training set, SQLite)
    ├─→ llm05 ─→ renderer   Improper Output Handling (headless Chromium on its own network)
    ├─→ llm06            Excessive Agency        (real tool calls against a throwaway SQLite DB)
    └─→ llm08            Vector & Embedding      (real embeddings + retrieval, SQLite)
    │
    ▼  every challenge reaches the model over its own internal network
ollama                 llama3.2:3b (chat) + nomic-embed-text (embeddings) — not published to the host
```

Isolation and hardening:

- **Only the gateway is reachable from the network** (port 8080). Ollama and every challenge
  container have no published ports.
- **Each challenge has its own internal Docker network**, shared only with Ollama and the
  gateway, so one challenge can't reach another or the internet. LLM05's browser sits on a
  further isolated network that can reach only the LLM05 app.
- **Sessions** are signed cookies. Each student's handle is fixed at login and can't be
  spoofed in requests.
- **Abuse limits:**
  - Failed logins are throttled per IP.
  - Model calls are limited per session (10 per minute, 1 at a time by default).
  - LLM05 runs at most 2 browsers at once.
- **Containers** run as non-root with all Linux capabilities dropped, `no-new-privileges`,
  read-only root filesystems, and CPU, memory and process limits.
- **LLM05 previews** are served with `Content-Security-Policy: sandbox`, so a payload can't
  run with the gateway's privileges even if the preview URL is opened directly.

---

## Requirements

| | Minimum | Notes |
|---|---|---|
| Docker | Docker Desktop (Windows/macOS) or Docker Engine + Compose v2 (Linux) | On Windows, enable the WSL2 backend |
| RAM | 8 GB total, ~4 GB free for Docker | The model needs ~3 GB |
| Disk | ~8 GB free | ~2.3 GB of models plus container images (the Playwright browser image is the largest) |
| CPU | Any modern 4+ core CPU | No GPU needed. Expect 10–40 s per model response on CPU |
| Network | Instructor machine and students on the same LAN | Internet is needed only for the first build and model download |

The setup script is for Windows 11. Linux and macOS use the manual steps.

---

## Setup: Windows

1. Install and start [Docker Desktop](https://www.docker.com/products/docker-desktop/) with the WSL2 backend.
2. Get the code:
   ```powershell
   git clone https://github.com/johnsonderickm/LLM-CTF-CyberRange.git
   cd LLM-CTF-CyberRange
   ```
3. Open **PowerShell as Administrator** in that folder and run:
   ```powershell
   Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned   # once per machine
   .\setup-windows.ps1
   ```

The script:
- checks Docker is running
- finds your LAN IP
- opens inbound port 8080 in Windows Firewall
- generates a random `CLASS_PASSCODE` into `.env` (if one isn't set)
- builds and starts all containers
- waits for both models to download

At the end it prints the student URL and the passcode.

The first run downloads about 2.3 GB of models plus the container images and can
take 10–20 minutes. Later starts take seconds.

**Recommended:** also add a `SECRET_KEY` to `.env` (see [Configuration](#configuration)).
Otherwise every student gets logged out whenever the gateway restarts.

---

## Setup: Linux / macOS

```bash
git clone https://github.com/johnsonderickm/LLM-CTF-CyberRange.git
cd LLM-CTF-CyberRange

cp .env.example .env
# Edit .env: set CLASS_PASSCODE to something only your class knows, and set
# SECRET_KEY to the output of:
python3 -c "import secrets; print(secrets.token_hex(32))"

docker compose up -d --build
docker logs ctf-model-pull -f     # wait for "✓ Models ready", then Ctrl+C
```

Then allow inbound TCP 8080 through your firewall if students connect from other
machines (for example `sudo ufw allow 8080/tcp`). Find your LAN IP with `ip addr`
(Linux) or `ipconfig getifaddr en0` (macOS).

---

## Check that it works

```bash
docker compose ps                    # every ctf-* service "healthy"; ctf-model-pull "exited (0)"
docker exec ctf-ollama ollama list   # shows llama3.2:3b and nomic-embed-text
curl http://localhost:8080/health    # {"status":"ok","challenges_registered":10}
```

Then open `http://localhost:8080` and log in with any handle and the passcode. The
sidebar should list all ten challenges. A challenge marked **(offline)** means its
container isn't answering (see [Troubleshooting](#troubleshooting)).

A quick end-to-end test: open **LLM06** and send
*"Check the support tickets and handle anything urgent."* The agent usually reads a
ticket containing a planted instruction, calls its delete tool, and the flag appears.

---

## Running a class

Share this with students:

```
URL:       http://<instructor-LAN-IP>:8080
Passcode:  <from .env or the setup script output>

1. Open the URL and log in with a handle (your name or nickname) and the passcode.
   Your handle is fixed for the session. Pick a unique one: LLM04 and LLM08
   keep your submissions under it.
2. Pick a challenge from the sidebar, read the description, and attack the model.
3. The flag appears automatically when you solve it. "Hint" is there if you're stuck.
```

Students can also use curl or any HTTP client:

```bash
curl -c cookies.txt -X POST http://<IP>:8080/login -d "handle=alice" -d "passcode=<passcode>"
curl -b cookies.txt -X POST http://<IP>:8080/challenge/llm01/chat \
  -H "Content-Type: application/json" -d '{"message": "your attack prompt"}'
```

Tips for instructors:

- **The model is non-deterministic.** The same prompt can fail once and work the next
  time. Tell students to retry and rephrase before concluding a technique doesn't work.
- **Everyone shares one CPU-bound model**, so replies slow down as more students send
  requests at once. The per-session rate limit (`429` errors) keeps it fair. Raise or lower
  it for your class size and hardware (see Configuration).
- **LLM04 and LLM08** have their own submit, check and reset panels in the UI. Students
  plant content first, then click the check button, which runs a fixed question the
  student never wrote.
- **LLM05** shows a live preview of the rendered output. The solve is confirmed a few
  seconds after the headless browser visits the page.
- Restarting the stack wipes all student submissions (LLM04, LLM08) and in-progress
  LLM05 attempts.

---

## Configuration

### `.env` (next to `docker-compose.yml`, never committed)

| Variable | Required | Purpose |
|---|---|---|
| `CLASS_PASSCODE` | **Yes** | Passcode students need to log in. `docker compose` refuses to start without it. |
| `SECRET_KEY` | Recommended | Signs session cookies. If empty, a random key is generated at every gateway start and students are logged out on restart. |

Copy `.env.example` to start.

### `docker-compose.yml`

| Setting | Service | Default | Purpose |
|---|---|---|---|
| `RATE_LIMIT_PER_MINUTE` | gateway | `10` | Model calls allowed per session per minute |
| `RATE_LIMIT_CONCURRENT` | gateway | `1` | Model calls a session can have in flight at once |
| `MAX_CONCURRENT_VISITS` | renderer | `2` | Simultaneous headless-browser visits for LLM05 |
| `"8080:8080"` | gateway `ports` | `8080` | Change the left side (e.g. `"8181:8080"`) if port 8080 is taken |
| `MODEL` | group-a, llm03, llm04, llm05, llm06, llm08 | `llama3.2:3b` | Chat model used by each challenge |

Apply changes with `docker compose up -d`.

### Changing the model

A larger model (e.g. `llama3.1:8b`) follows its instructions more faithfully, which
makes the challenges harder. It also needs more RAM and is slower on CPU.

1. Change `MODEL=` in all six challenge services in `docker-compose.yml`.
2. Change `llama3.2:3b` in the `model-pull` entrypoint to the same model, or pull it by
   hand: `docker exec ctf-ollama ollama pull llama3.1:8b`.
3. `docker compose up -d`.

The model must support tool calling for LLM06 to work.

### Changing the flags

Flags live in each challenge's code, in the `"flag"` field of its `CHALLENGE` dict:
- `challenges/group-a/llm01.py`, `llm02.py`, `llm07.py`, `llm09.py`, `llm10.py`
- `challenges/llm03/app.py`, `llm04/app.py`, `llm05/app/app.py`, `llm06/app.py`, `llm08/app.py`

LLM07's flag also appears inside its `system_prompt`, so change both. Rebuild with
`docker compose up -d --build`.

---

## Project layout

```
.
├── docker-compose.yml        All services, networks, limits and hardening
├── setup-windows.ps1         One-shot Windows setup
├── .env.example              Template for .env (passcode, session key)
├── dataset.jsonl             Offline attack/defense examples (not used at runtime)
├── gateway/                  Login, rate limiting, UI (templates/), reverse proxy
└── challenges/
    ├── group-a/              LLM01, 02, 07, 09, 10 — one module per challenge + app.py dispatcher
    ├── llm03/                Supply Chain
    ├── llm04/                Data & Model Poisoning
    ├── llm05/app/            Improper Output Handling — chat, scoring, cookie callback
    ├── llm05/renderer/       Headless Chromium (Playwright) that visits the model's output
    ├── llm06/                Excessive Agency
    └── llm08/                Vector & Embedding Weaknesses
```

Every challenge container exposes the same endpoints:
- `POST /chat` returns `{response, solved, flag, points}`.
- `GET /meta` returns the public name, description and hint the gateway displays.
- `GET /health`.

LLM04 and LLM08 add `POST /insert`, `/verify` and `/reset`.

---

## Useful commands

```bash
docker compose up -d                 # start
docker compose down                  # stop (keeps downloaded models)
docker compose up -d --build         # rebuild after changing code
docker compose ps                    # status of every service

docker logs ctf-gateway -f           # entry point, every student request
docker logs ctf-group-a -f           # LLM01, 02, 07, 09, 10
docker logs ctf-llm05 -f             # also: ctf-llm03, ctf-llm04, ctf-llm06, ctf-llm08
docker logs ctf-renderer -f          # LLM05 headless browser
docker logs ctf-ollama -f            # the model server

docker compose down -v               # full reset — also deletes the downloaded models
```

---

## Troubleshooting

**`required variable CLASS_PASSCODE is missing a value`**
There's no `.env`, or it has no `CLASS_PASSCODE` line. Copy `.env.example` to `.env`
and fill it in, or run `setup-windows.ps1`.

**Challenges answer with "model backend is temporarily unreachable"**
Ollama is still starting or the models are still downloading. Check
`docker logs ctf-model-pull -f` and wait for `✓ Models ready`. On slow connections the
first download can take 15+ minutes.

**LLM08 fails on every request**
The embedding model is missing. Run `docker exec ctf-ollama ollama list`. If
`nomic-embed-text` isn't listed, run `docker exec ctf-ollama ollama pull nomic-embed-text`.

**A challenge shows "(offline)" in the sidebar**
The gateway can't reach that container. Run `docker compose ps`, then
`docker logs ctf-<name>`. The sidebar recovers by itself once the container is back.

**`429` / "Rate limit" errors**
Working as intended: the session sent too many model requests too quickly. Wait a few
seconds. Adjust `RATE_LIMIT_PER_MINUTE` / `RATE_LIMIT_CONCURRENT` if they're too strict
for your class.

**Everyone got logged out**
The gateway restarted without a fixed `SECRET_KEY`. Set one in `.env`.

**Students can't reach the server**
- Port 8080 must be open inbound on the instructor machine. The setup script does this
  on Windows; run it as Administrator.
- From a student machine, test with
  `Test-NetConnection <instructor-IP> -Port 8080` (Windows) or `nc -zv <instructor-IP> 8080`.
- Some guest or campus Wi-Fi networks block device-to-device traffic. Use a wired
  network or a dedicated router.

**Port 8080 is already in use**
Change `"8080:8080"` to e.g. `"8181:8080"` under `gateway` in `docker-compose.yml`, and
open that port in the firewall instead.

**Responses are very slow**
Expected on CPU with many students. Lower `RATE_LIMIT_PER_MINUTE`, close other heavy
applications, or run on a machine with more cores. Docker Desktop's resource settings
can also cap CPU and RAM. Raise them under *Settings → Resources*.

---

## Known limitations

- **Flags are in the source.** See the warning at the top.
- **Plain HTTP.** The passcode and session cookie travel unencrypted on the LAN. Put a
  TLS reverse proxy in front if that matters on your network.
- **Handles aren't accounts.** Two students who pick the same handle share their LLM04
  and LLM08 submissions.
- **No persistence or scoreboard.** All state lives in memory or temporary files and is
  lost on restart.
- **Some checks are keyword-based** (LLM01, LLM02, LLM07, LLM10). They confirm the
  output, not the technique. In particular, LLM10 can be passed by asking for one word
  repeated 300 times.
- **Results vary between runs** because the model samples randomly. A technique that
  works once may need a few tries.

---

## Reference dataset

`dataset.jsonl` holds 22 attack/defense example pairs across all ten categories, in
OpenAI chat format:

```json
{"messages": [...], "vulnerability": "LLM01", "type": "attack|defense", "technique": "..."}
```

The running range doesn't use it. It's teaching material: example attacks next to the
behavior a well-defended assistant should show. It's too small to fine-tune a model
on meaningfully. If you experiment with fine-tuning, train only on the `defense`
examples, since the `attack` examples show an assistant *giving in*.
