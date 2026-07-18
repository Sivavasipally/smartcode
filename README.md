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

```bash
uv sync                       # core (all providers except local torch)
uv sync --extra local         # + torch (CPU) for the local Qwen SLM

# CUDA torch instead (recommended if you have an NVIDIA GPU):
uv pip install torch --index-url https://download.pytorch.org/whl/cu121
```

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

smartcode gen "FastAPI endpoint POST /users with pydantic model" \
    --lang python --framework fastapi --out app/users.py -p groq

smartcode modify src/app.ts "add rate limiting to all routes" -p local
smartcode review pkg/handler.go -p anthropic
```

Common flags: `-p/--provider local|groq|anthropic|openai|google|mock`,
`--risk low|medium|high` (write-gate tier), `--accept "<criterion>"`
(repeatable acceptance criteria), `--test-cmd "pytest -q"`,
`--yes` (auto-approve writes), `--verbose` (live per-node trace).

Exit code is 0 for `success`/`best_effort`, 1 otherwise — scriptable in CI.

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

- **Parameters panel** — Generate / Modify / Review tabs, objective, provider
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
- **HITL approval dialog** — risk-tiered writes pause the graph and show each
  pending edit (action, path, anchor, summary) for Approve / Reject.
- **Result view** — status banner, findings, written-file code, downloadable
  evidence-package JSON.

```bash
cd ui
npm install
npm start          # spawns the Python agent (uv) as a stdio sidecar
npm run smoke      # headless self-check: Electron + Python bridge handshake
```

The UI talks to `python -m smartcode.uiserver` over **line-delimited JSON on
stdio** — no ports, no extra Python dependencies. Opening
`ui/renderer/index.html` in a plain browser runs a canned **demo mode** for UI
development without Electron or Python.

## How it works — one LangGraph StateGraph

```
START → classify_intent ─┬─(new)────────────→ planner ─┐
                         ├─(modify)→ retriever→ planner┤
                         └─(review)→ retriever ──→ critic ──→ finalize
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
                  hitl_gate (risk-tiered write approval)
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
| 2 | `retriever` | no | tree-sitter parses targets into **symbols**; rerank-and-budget picks only relevant ones; builds a compact repo map; **sufficiency gate** halts if context is inadequate | just-in-time context — modifying a 2,000-line file doesn't cost 2,000 lines of tokens, and the coder never hallucinates over missing files |
| 3 | `planner` | yes | ≤6 bounded, verifiable steps anchored to real symbols; unknowns go to `open_questions`, never guessed | Plan–Execute–Verify under an authority-layered prompt (policy > contract > skill > retrieved > scratchpad) |
| 4 | `coder` | yes | emits **structured `CodeEdit`s** (create/replace/insert/delete, anchored to symbol or line range) — not prose; small models use a code-fence path instead of JSON | deterministic, reproducible, reviewable edits; capability-aware degradation down to a 1.5B SLM |
| 5 | `verifier` | **no** | virtual-apply edits in memory, then: tree-sitter AST check, `py-compile`, linters (ruff/tsc/node/gofmt), your test command — all sandboxed | the **deterministic sensor**: ground truth a model can't sweet-talk; nothing touches disk yet |
| 6 | `critic` | yes | LLM judge scores against **acceptance criteria**; findings with severity + suggestion; may not overrule the sensor; fails open (capped at `best_effort`) | inferential review — catches "compiles but wrong" |
| 7 | `repair` | no | folds verify+critique failures into feedback, records **failed approaches** in the scratchpad, compacts memory, loops back to coder (bounded by `max_revisions`) | self-correction that doesn't repeat mistakes and can't loop forever |
| 8 | `hitl_gate` | no | risk-tiered approval: low auto, medium confirm (CLI prompt / UI dialog), high explicit-only | a human owns every risky write; the graph genuinely pauses |
| 9 | `finalize` | no | writes approved files (writable-roots enforced one last time), assembles + persists the **EvidencePackage** | full auditability: any run reconstructable from `.smartcode/runs/` |

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
