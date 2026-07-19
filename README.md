# smartcode

A local-first, multi-provider **code-generation agent** built on LangGraph 1.x,
with a CLI, a Python library, and an Electron desktop UI that visualizes the
pipeline live.

It generates **new** code, **modifies/updates** existing code, and **reviews**
code across many languages and frameworks — driven by a local Qwen2.5-1.5B SLM
or by Groq / Anthropic Claude / Google Gemini / OpenAI.

The design implements the agent-, pipeline-, prompt- and context-engineering
patterns from the 2026 harness/context-engineering references (see the
[pattern map](#pattern-map-reference-docs--code)).

---

## Install

### One-shot setup (Python + UI together)

With **uv** (recommended):

```bash
uv sync && npm install --prefix ui
```

With **pip** (uses the pinned [requirements.txt](requirements.txt)):

```bash
# Windows (PowerShell)
python -m venv .venv; .venv\Scripts\activate
pip install -r requirements.txt -e . ; npm install --prefix ui

# macOS / Linux
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -e . && npm install --prefix ui
```

That's everything: CLI (`smartcode …`), library, tests (`pytest`), and the
desktop app (`npm start --prefix ui`).

### Local SLM extra (torch)

Only needed for the `local` Qwen provider:

```bash
uv sync --extra local                 # uv, CPU wheel
pip install torch                     # pip, CPU wheel
# CUDA instead (recommended with an NVIDIA GPU):
pip install torch --index-url https://download.pytorch.org/whl/cu121
```

`requirements.txt` is exported from the uv lockfile (pinned, reproducible) —
regenerate it after dependency changes with
`uv export --format requirements-txt --no-hashes --no-emit-project -o requirements.txt`.

Copy `.env.example` to `.env` and fill in the keys for the providers you use.

> **.env rules**
> - Keys like `GROQ_API_KEY` are loaded into the process environment
>   automatically (`load_settings()` calls `load_dotenv()`).
> - Keep comments on their **own line** — inline `VALUE  # comment` is not
>   reliably stripped and becomes part of the value.

The local provider only needs the model checkpoint (default
`D:/models/Qwen2.5-1.5B-Instruct`, override with `SMARTCODE_LOCAL_MODEL_PATH`).

## Quick start

```bash
smartcode doctor              # env, keys, grammars, local model, torch
smartcode providers           # provider availability / active model
smartcode runs                # recent runs from the evidence ledger

# explicit output path — writes exactly there
smartcode gen "FastAPI endpoint POST /users with pydantic model" \
    --lang python --framework fastapi --out app/users.py -p groq

# no --out: the agent scans the codebase (--root, default .), PROPOSES the
# folder + file name(s) — plus any wiring edits — and asks before generating
smartcode gen "a rate-limiter middleware" --root . -p groq

smartcode modify src/app.ts "add rate limiting to all routes" -p local
smartcode review pkg/handler.go -p anthropic

# folder-scale: scan every repo under --root, review the proposed change-set,
# approve / narrow / send suggestions — then it codes
smartcode ws "add structured logging to every service entrypoint" \
    --root D:/projects -p groq
```

Common flags: `-p/--provider local|groq|anthropic|openai|google|mock`,
`--risk low|medium|high` (write-gate tier), `--accept "<criterion>"`
(repeatable acceptance criteria), `--test-cmd "pytest -q"`,
`--yes` (auto-approve writes), `--verbose` (live per-node trace).

Exit code is 0 for `success`/`best_effort`, 1 otherwise — scriptable in CI.
Every run prints a **colored unified diff** of what changed (also shown in the
approval prompt before anything is written), and every run is queryable later
via `smartcode runs`.

> Rebuilding from scratch? **[recreate.md](recreate.md)** is a complete
> functional specification of the whole application.

## Examples

### Simple — one-liners

```bash
# generate a small utility (language inferred from --out)
smartcode gen "slugify(text): lowercase, strip accents, join words with '-'" \
    --out utils/slug.py -p groq --yes

# quick review of one file
smartcode review src/payment.py -p groq

# works fully offline with the deterministic stub (demos, CI smoke)
smartcode gen "a is_even function" --lang python --out tmp/even.py -p mock --yes
```

```python
from smartcode import generate
ev = generate("a debounce decorator", language="python",
              out_path="utils/debounce.py", provider="groq")
print(ev.status)
```

### Medium — frameworks, acceptance criteria, modify

```bash
# framework-aware generation: fastapi.md skill steers APIRouter/pydantic/201
smartcode gen "endpoint POST /users with a pydantic model and email validation" \
    --lang python --framework fastapi --out app/users.py \
    --accept "returns 201 with the created user" \
    --accept "invalid email returns 422" \
    -p groq --verbose

# modify existing code — tree-sitter loads only the relevant symbols
smartcode modify src/middleware.ts "add rate limiting to all routes" \
    --framework express -p groq

# react component with the local SLM (no API key, no network)
smartcode gen "a Toggle component with label and onChange" \
    --lang typescript --framework react --out src/Toggle.tsx -p local --yes
```

```python
from smartcode import CodeAgent

agent = CodeAgent(provider="groq")
ev = agent.modify(
    ["src/api.py"],
    "add input validation to create_user",
    acceptance=["existing routes unchanged", "invalid payloads rejected with 422"],
)
for f in ev.critique.findings:
    print(f.severity, f.message)
```

### Complex — multi-file, tests-as-gate, custom approval, event streaming

```bash
# high-risk change across several files: verification must pass YOUR tests,
# and the write gate demands explicit approval (no --yes allowed to skip high)
smartcode modify src/auth.py src/session.py \
    "rotate refresh tokens on every use and invalidate the old family on reuse" \
    --risk high \
    --accept "token reuse triggers family invalidation" \
    --accept "all existing auth tests still pass" \
    --test-cmd "pytest tests/auth -q" \
    -p anthropic --verbose

# focused security review, findings only
smartcode review src/upload.py src/storage.py \
    --focus "path traversal, unrestricted file types, missing size limits" -p groq
```

```python
# Library power-use: custom approval policy + live event stream + evidence audit
from smartcode import CodeAgent

def approve(task, edits, files):
    # e.g. auto-approve unless an edit touches more than 100 lines
    return all(len(e.get("content", "").splitlines()) <= 100 for e in edits)

agent = CodeAgent(
    provider="anthropic",
    approval_callback=approve,
    on_event=lambda e: print(f"[{e['elapsed_s']:>6.1f}s] {e['node']:<16} {e['message']}"),
    max_revisions=5,
    test_command="pytest -q",
)
ev = agent.generate(
    "a rate limiter: sliding window, redis backend, decorator API, full type hints",
    language="python", out_path="lib/ratelimit.py",
    acceptance=[
        "thread-safe under concurrent calls",
        "falls back to in-memory storage when redis is unreachable",
        "100% of public functions typed and docstringed",
    ],
)
print(ev.status, ev.revisions)                 # e.g. success 1
print(ev.model_dump_json(indent=2))            # the full evidence package
```

## Library

```python
from smartcode import CodeAgent

agent = CodeAgent(provider="groq")
evidence = agent.generate(
    "binary search over a sorted list, with tests",
    language="python", out_path="algo/search.py",
)
evidence = agent.modify(["src/api.py"], "add input validation to create_user")
evidence = agent.review(["src/api.py"], focus="security issues")

print(evidence.status)                       # success | best_effort | rejected | review_only
print([a.path for a in evidence.applied])    # what was actually written
```

Every run returns an `EvidencePackage` (task contract, plan, edits,
verification results, critique, what was written) and is journaled to
`.smartcode/sessions.db` (LangGraph sqlite checkpointer) plus
`.smartcode/runs/*.jsonl` and `.smartcode/runs/evidence-*.json`.

## Desktop UI (Electron)

A desktop app that exposes **every parameter** and shows **every internal node
of the generation flow, live**:

- **Parameters panel** — Generate / Modify / Review / **Workspace** tabs
  (workspace: native folder picker over a multi-repo root), objective, provider
  picker with live availability + model badges, language/framework, output
  path or target files (native dialogs), acceptance-criteria chips, risk tier,
  max revisions, test command, linter/test toggles.
- **Live pipeline flow** — the actual LangGraph topology as an animated node
  graph: pulsing `● RUNNING` node, `✓ DONE` / `✕ FAILED` / `– SKIPPED` states,
  animated active edge, and a `×N` badge on the Repair loop counting
  revisions.
- **Event ledger** — every node event, timestamped; click one to inspect the
  node's output: plan steps, verifier checks (AST / lint / tests), critique
  score + findings with severity and suggestions, applied files.
- **Change-set proposal dialog** *(workspace runs)* — before any generation,
  review the proposed files with per-file checkboxes, the selector's reasons
  and open questions; approve the selection, or type suggestions and
  **Re-propose** — the run loops back with your guidance.
- **HITL approval dialog** — risk-tiered writes pause the graph and show each
  pending edit (action, path, anchor, summary) **with a colored unified
  diff** for Approve / Reject (Escape rejects, never approves).
- **Result view** — status banner, findings, per-file **diff view**
  (`+adds/−dels`), written-file code, "Show in folder", downloadable
  evidence-package JSON.
- **History tab** — every past run from the evidence ledger; click one to
  reopen its result and diffs.
- Quality-of-life: Ctrl+Enter runs, the form persists across restarts.

### Configure & run the desktop app

**Prerequisites**

1. **Node.js ≥ 18** (`node --version`) and npm.
2. **uv on PATH** (`uv --version`) — the app launches the Python agent with
   `uv run`, from the repo root.
3. Python side installed once from the repo root: `uv sync`
   (add `--extra local` if you'll use the local Qwen provider).
4. Providers configured in `.env` at the **repo root** (same file the CLI
   uses — copy `.env.example`, add e.g. `GROQ_API_KEY=...`). No UI-specific
   configuration exists; the UI reads everything through the agent.

**Install & start**

```bash
cd ui
npm install        # one-time: installs Electron
npm start          # opens the window and spawns the Python agent sidecar
```

On launch the header should show a green dot with **"agent ready"**, and the
Provider dropdown fills in with availability badges (● usable / ○ missing
key). Pick provider, mode, and parameters on the left, then **Run pipeline**
(or Ctrl+Enter). `medium`/`high` risk runs pause at the approval dialog with
a diff before anything is written.

**Verify / troubleshoot**

```bash
npm run smoke      # headless self-check: prints SMOKE_OK when Electron
                   # can spawn the bridge and receive its "ready" handshake
```

| Symptom | Fix |
|---|---|
| Header says "agent exited" | `uv` not on PATH, or `uv sync` never ran — run `uv run python -m smartcode.uiserver` manually from the repo root and read the error; then "Restart agent" in the header |
| Provider shows ○ unavailable | key missing from the repo-root `.env` (hint text shows the reason); restart the agent after editing `.env` |
| Local provider unavailable | `uv sync --extra local` + check `SMARTCODE_LOCAL_MODEL_PATH` |
| Runs never finish on `local` | CPU inference is minutes-per-node; install the CUDA torch wheel or use a cloud provider |

**How it's wired**: the UI talks to `python -m smartcode.uiserver` over
**line-delimited JSON on stdio** — no ports, no HTTP server, no extra Python
dependencies; closing the window shuts the agent down. Opening
`ui/renderer/index.html` in a plain browser runs a canned **demo mode** for
UI development without Electron or Python.

## Real sessions & recipes

Everything below is genuine output from runs of this repo (trimmed for width).

### 1. Cloud provider, clean pass (Groq · llama-3.3-70b-versatile)

```
$ smartcode gen "FastAPI endpoint POST /users with pydantic model" \
      --lang python --framework fastapi --out app/users.py -p groq --yes --verbose

   0.2s classify_intent  intent=new lang=python framework=fastapi
   2.1s planner          5 step(s): Create a new FastAPI endpoint POST /users …
   2.7s coder            1 edit(s)
   2.8s verifier         PASS
   3.2s critic           score=1.00 revise=False findings=0
   3.2s hitl_gate        tier=medium -> approved
   3.3s finalize         status=success written=1
```

Generated `app/users.py` — note the fastapi skill steering (`APIRouter`,
`response_model`, `status_code=201`):

```python
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

class User(BaseModel):
    id: int
    name: str
    email: str

@router.post('/users/', response_model=User, status_code=201)
def create_user(user: User):
    return user
```

### 2. Self-correction loop caught by the harness (weaker 8B model)

The same request on `llama-3.1-8b-instant` shows why the deterministic sensor
exists — ruff catches a real bug, the repair loop feeds it back, and when the
model still can't fix it the run is **honestly** downgraded, never silently
"done":

```
   …
   verifier   FAIL lint failures: app\users.py: F821 Undefined name `app`
   repair     revision 1: 1 issue(s) fed back
   coder      1 edit(s)
   …after 3 bounded revisions…
   critic     score=0.00  findings=1
     blocker: Undefined name `app` (app/users.py)
         -> Import the FastAPI app instance or pass it as a dependency
   finalize   status=best_effort written=1
```

Exit code 0 vs 1 plus the `status` field lets scripts distinguish these.

### 3. Fully offline: local Qwen2.5-1.5B, no network, no keys

```
$ smartcode gen "a python function is_palindrome(s) that ignores case and
  non-alphanumeric characters" --lang python --out demo/palindrome.py -p local --yes -v

 164.6s planner   5 step(s): Start with defining the function…
 363.2s coder     JSON contract failed; code-fence fallback used
 363.2s coder     1 edit(s)
 364.6s verifier  PASS
 442.9s critic    score=0.00 revise=False findings=0     ← 1.5B judge unavailable
 443.2s finalize  status=best_effort written=1
```

The 1.5B model can't emit code-inside-JSON, so the **code-fence path**
produced the edit; the code itself passed AST + ruff and is correct
(`re.sub(r'[^a-zA-Z0-9]','',s).lower()` + reversal check). `best_effort`
(not `success`) because the tiny judge couldn't verify acceptance — the
harness never claims more than it proved. Times are CPU; a GPU or any cloud
provider is orders faster.

### 4. The audit trail

```
$ smartcode runs
| when                | status      | intent | rev | objective                        |
| 2026-07-19T05-33-02 | success     | modify | 0   | replace old with solve           |
| 2026-07-18T19-00-54 | success     | new    | 0   | FastAPI endpoint POST /users …   |
| 2026-07-18T16-11-01 | best_effort | new    | 0   | a python function is_palindrome… |
```

Each row is backed by a full `evidence-*.json` (contract, plan, edits, diffs,
verification, critique) — e.g. pull every failed check from a run:

```bash
python -c "import json;d=json.load(open('.smartcode/runs/evidence-2026-07-19T05-33-02.json'));\
print([c['name'] for c in d['verify']['checks'] if not c['passed']])"
```

### 5. Recipe — CI quality gate (GitHub Actions)

```yaml
- name: smartcode review changed files
  env:
    GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}
  run: |
    uv sync
    CHANGED=$(git diff --name-only origin/main -- '*.py' | tr '\n' ' ')
    [ -z "$CHANGED" ] || uv run smartcode review $CHANGED \
        --focus "bugs, security, missing error handling" -p groq
```

`review` never writes; findings land in the job log and the evidence ledger.

### 6. Recipe — batch modernisation with the library

```python
from pathlib import Path
from smartcode import CodeAgent

agent = CodeAgent(provider="groq", default_risk_tier="low")   # low = auto-apply
for f in Path("src").rglob("*.py"):
    ev = agent.modify([str(f)], "add type hints to all public functions",
                      acceptance=["behaviour unchanged", "mypy-clean annotations"])
    print(f"{f}: {ev.status} ({ev.revisions} revisions)")
```

Every file still passes the full verify→critique pipeline individually, and
each write is journaled with its diff.

## Workspace mode — point it at a folder of repos

`smartcode ws` (CLI) and the **Workspace** tab (desktop app) operate on a whole
folder that may contain **multiple repos**:

1. **Scan** — every repo under the root is discovered (`.git`, `pyproject.toml`,
   `package.json`, `go.mod`, … markers), source files indexed with tree-sitter
   symbols, candidates ranked against your objective (capped + budgeted, so
   thousand-file workspaces stay cheap).
2. **Propose** — the selector LLM proposes the change-set: which files to
   create/modify and *why*, grounded in the index — a path it invented cannot
   survive validation.
3. **Review** — the run pauses and shows you the proposed files **before any
   code is generated**. You can approve, untick files to narrow the set,
   or send suggestions ("auth-service only, skip web-app") — suggestions
   re-run the selection with your guidance (bounded rounds).
4. **Proceed** — the approved set becomes the contract's writable paths and the
   normal pipeline runs: retrieve → plan → code → verify → critique →
   **write gate with diffs** → finalize. Two gates, two questions: *right
   files?* then *right changes?*

The same proposal flow powers **generate without an output path**: the agent
identifies the conventional folder + file name for the new code (and the
existing files that need wiring edits — exports, routers, registries), shows
them for approval, then generates. In the desktop app, leave "Output file"
empty and pick the codebase folder.

```python
from smartcode import CodeAgent

def review_targets(task, proposal, round_no):
    print([f"{t.action} {t.path} — {t.reason}" for t in proposal.targets])
    return {"decision": "approve"}                    # or "revise"/"reject"

agent = CodeAgent(provider="groq", proposal_callback=review_targets)
ev = agent.workspace("add health-check endpoints to all services",
                     root="D:/projects")
```

## How it works — one LangGraph StateGraph

```
START → classify_intent ─┬─(new)────────────→ planner ─┐
                         ├─(modify)→ retriever→ planner┤
                         ├─(review)→ retriever ──→ critic ──→ finalize
                         └─(workspace)→ select_targets → proposal_gate
                                            ▲   revise ◀──┘   │approve
                                            └────────────── retriever → planner
                                                       │
                               ┌────── coder ◀─────────┘
                               ▼
                         verifier  (deterministic sensor: tree-sitter AST,
                               │    linters, optional tests)
                    ┌──────────┴───────────┐
                  pass                  fail (budget left)
                    │                       │
                  critic (LLM judge) ◀── repair (feedback → scratchpad)
                    │        │revise            ▲
                    │        └──────────────────┘
                  hitl_gate (risk-tiered write approval, diffs shown)
                    │
                  finalize (apply edits, evidence package) → END
```

- **new**: plan → generate structured `CodeEdit`s → verify → critique → write.
- **modify/update**: tree-sitter parses the target files into symbols; only the
  relevant symbols are loaded into context (just-in-time / progressive
  disclosure); the coder emits anchored edits (symbol or line-range), applied
  deterministically — never whole-prose rewrites.
- **review**: retrieve → critic only; findings with severity, no writes.

### What each node does and achieves

Full deep dive with inputs/outputs, failure routing and a worked trace:
**[docs/PIPELINE.md](docs/PIPELINE.md)**. In one screen:

| # | Node | LLM? | Task | What it achieves |
|---|------|------|------|------------------|
| 1 | `classify_intent` | rarely | resolve intent, infer language, load language+framework **skill files**, init scratchpad, validate the contract | supervisor routing + procedural memory: the model gets expert framework guidance for free |
| 1a | `select_targets` *(workspace)* | yes | scan all repos under the root, rank candidate files, LLM proposes the change-set (create/modify + reason), validated against the index | folder-scale targeting that cannot hallucinate paths |
| 1b | `proposal_gate` *(workspace)* | no | pause for review: approve / narrow the file set / send suggestions (bounded re-proposal rounds) | the human owns *which files change* before any code is generated |
| 2 | `retriever` | no | tree-sitter parses targets into **symbols**; rerank-and-budget picks only relevant ones; builds a compact repo map; **sufficiency gate** halts if context is inadequate | just-in-time context — modifying a 2,000-line file doesn't cost 2,000 lines of tokens, and the coder never hallucinates over missing files |
| 3 | `planner` | yes | ≤6 bounded, verifiable steps anchored to real symbols; unknowns go to `open_questions`, never guessed | Plan–Execute–Verify under an authority-layered prompt (policy > contract > skill > retrieved > scratchpad) |
| 4 | `coder` | yes | emits **structured `CodeEdit`s** (create/replace/insert/delete, anchored to symbol or line range) — not prose; small models use a code-fence path instead of JSON | deterministic, reproducible, reviewable edits; capability-aware degradation down to a 1.5B SLM |
| 5 | `verifier` | **no** | virtual-apply edits in memory, compute **unified diffs vs disk**, then: tree-sitter AST check, `py-compile`, linters (ruff/tsc/node/gofmt), your test command — all sandboxed | the **deterministic sensor**: ground truth a model can't sweet-talk; nothing touches disk yet |
| 6 | `critic` | yes | LLM judge reviews the **materialized files** (not raw edit JSON) against **acceptance criteria**; findings with severity + suggestion; may not overrule the sensor; fails open (capped at `best_effort`) | inferential review — catches "compiles but wrong" |
| 7 | `repair` | no | folds verify+critique failures into feedback, records **failed approaches** in the scratchpad, compacts memory, loops back to coder (bounded by `max_revisions`) | self-correction that doesn't repeat mistakes and can't loop forever |
| 8 | `hitl_gate` | no | risk-tiered approval with the **diff shown up front**: low auto, medium confirm (CLI prompt / UI dialog), high explicit-only | a human owns every risky write; the graph genuinely pauses |
| 9 | `finalize` | no | writes approved files (writable-roots enforced one last time), assembles + persists the **EvidencePackage** incl. diffs | full auditability: any run reconstructable from `.smartcode/runs/` (`smartcode runs`, UI History tab) |

Statuses are honest by construction: `success` requires the deterministic
sensor **and** the LLM judge **and** the write gate to pass; anything less is
`best_effort` (written, gates incomplete) or `rejected` (nothing written).

**Languages** (tree-sitter grammars installed): Python, JavaScript, TypeScript,
Go, Rust, Java, C, C++, C#, Ruby, PHP — plus framework skill files for React,
FastAPI, Flask, Spring, Express (user overrides in
`.smartcode/skills/{languages,frameworks}/*.md`). Other languages still work
through the generic path (bracket-balance check instead of AST).

## Providers

| id | backing | needs | default model |
|----|---------|-------|---------------|
| `local` | Qwen2.5-1.5B via transformers | `--extra local` (torch), model dir | Qwen2.5-1.5B-Instruct |
| `groq` | langchain-groq | `GROQ_API_KEY` | llama-3.3-70b-versatile |
| `anthropic` | langchain-anthropic | `ANTHROPIC_API_KEY` | claude-sonnet-4-5 |
| `openai` | langchain-openai | `OPENAI_API_KEY` | gpt-4.1 |
| `google` | langchain-google-genai | `GOOGLE_API_KEY` | gemini-2.0-flash |
| `mock` | deterministic stub | nothing (offline/tests) | — |

Override models with `SMARTCODE_<PROVIDER>_MODEL`. Cloud providers use native
structured output; the local SLM and mock use a JSON-contract fallback with
schema validation + bounded repair retries. For the **coder** role, small
models (`small_model = True`) skip JSON entirely and emit a plain fenced code
block that smartcode wraps into a structured edit itself — 1–2B models cannot
reliably escape whole files inside JSON strings.

> Model quality matters more than the harness: with `llama-3.3-70b-versatile`
> a typical generate run completes in seconds at score 1.0; with
> `llama-3.1-8b-instant` or the local 1.5B expect repair loops and
> `best_effort` outcomes. The harness reports honestly either way.

## Pattern map (reference docs → code)

| Pattern | Where |
|---|---|
| Task Contract | `models.TaskContract` (+ `validate_contract`) |
| Plan–Execute–Verify | `graph/` planner → coder → verifier |
| Deterministic Sensor | `verify/ast_checks.py`, `verify/linters.py` |
| Inferential Reviewer / LLM Judge | `graph/nodes.py::critic` |
| Evaluator–Optimizer / Self-Correction loop | verifier→repair→coder cycle (bounded by `max_revisions`) |
| Durable State & Session Ledger | `graph/checkpointer.py` (sqlite), `state.events` |
| Evidence Package | `models.EvidencePackage`, saved per run |
| Supervisor / Routing | `graph/supervisor.py` |
| Sandboxed Execution | `verify/runner.py` (subprocess, timeout, cwd jail) |
| Risk-tiered HITL write gate | `graph/nodes.py::hitl_gate` + UI approval dialog |
| Authority-Layered Context | `context/authority.py` |
| Context Contract + Sufficient Context Gate | `context/contract.py`, `retrieval/context_budget.py` |
| Structured Scratchpad | `models.StructuredScratchpad`, updated by repair |
| Just-in-Time / Progressive Disclosure | `retrieval/tree_sitter.py`, `retrieval/repo_map.py` |
| Rerank-and-Budget | `retrieval/context_budget.py` |
| Loss-Aware Compaction / Sliding Window | `context/compaction.py` |
| Skills & Procedural Memory | `skills/` (per-language/framework markdown) |
| Output Contract (schema-first) | `providers/base.py::invoke_structured` |
| Capability-aware degradation | `small_model` fence path, critic fail-open, provider health checks |

## Project layout

```
src/smartcode/
  agent.py          CodeAgent facade (generate / modify / review)
  cli.py            Rich CLI: gen | modify | review | providers | doctor
  uiserver.py       stdio JSON bridge for the Electron UI
  config.py         pydantic-settings (SMARTCODE_* env), .env loading
  models.py         typed contracts: TaskContract, Plan, CodeEdit, VerifyResult, …
  editing.py        deterministic anchored-edit application
  providers/        base + local_qwen, groq, anthropic, openai, google, mock
  context/          authority layers, context contracts, compaction
  retrieval/        tree-sitter symbols, repo map, rerank-and-budget
  skills/           per-language / per-framework procedural memory (markdown)
  verify/           AST sensor, linters, tests, sandboxed runner
  graph/            state, nodes, supervisor routing, builder, checkpointer
ui/                 Electron app (main.js, preload.js, renderer/)
examples/           runnable demos (offline, mock provider)
tests/              23 tests: symbols, sensor, edits, mock end-to-end
```

## Tests

```bash
uv run pytest
```

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `provider 'X' unavailable: missing X_API_KEY` | Key not in `.env`/environment; check `smartcode providers` |
| A `#` or comment text executed as the test command | Inline comment in `.env` — move comments to their own line |
| Local provider slow (minutes per node) | CPU torch; install the CUDA wheel (see Install) |
| `local` unavailable | `uv sync --extra local`; verify `SMARTCODE_LOCAL_MODEL_PATH` |
| npm-installed linters (tsc/eslint) not detected on Windows | They are `.cmd` shims; smartcode resolves them via `PATH` — ensure the npm global bin dir is on `PATH` |
| Lots of repair loops / `best_effort` | Model too small for the task; use a stronger model (see Providers note) |
