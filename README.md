# smartcode

A local-first, multi-provider **code-generation agent** built on LangGraph 1.x.
It generates **new** code, **modifies/updates** existing code, and **reviews** code
across many languages and frameworks — driven by a local Qwen2.5-1.5B SLM or by
Groq / Anthropic Claude / Google Gemini / OpenAI.

The design implements the agent-, pipeline-, prompt- and context-engineering
patterns from the 2026 harness/context-engineering references (see the pattern
map at the bottom).

## Install

```bash
uv sync                       # core (all providers except local torch)
uv sync --extra local         # + torch (CPU) for the local Qwen SLM
# CUDA torch instead (Pascal+ GPU):
uv pip install torch --index-url https://download.pytorch.org/whl/cu121
```

Copy `.env.example` to `.env` and fill in the keys for the providers you use.
The local provider only needs the model checkpoint (default
`D:/models/Qwen2.5-1.5B-Instruct`, override with `SMARTCODE_LOCAL_MODEL_PATH`).

## CLI

```bash
smartcode gen "FastAPI endpoint POST /users with pydantic model" --lang python --framework fastapi --out app/users.py -p groq
smartcode modify src/app.ts "add rate limiting to all routes" -p local
smartcode review pkg/handler.go -p anthropic
smartcode providers      # provider availability / health
smartcode doctor         # env, keys, grammars, local model smoke check
```

Common flags: `-p/--provider local|groq|anthropic|openai|google|mock`,
`--risk low|medium|high` (write-gate tier), `--yes` (auto-approve writes),
`--verbose` (per-node trace).

## Library

```python
from smartcode import CodeAgent

agent = CodeAgent(provider="groq")
evidence = agent.generate(
    "binary search over a sorted list, with tests",
    language="python", out_path="algo/search.py",
)
evidence = agent.modify(["src/api.py"], "add input validation to create_user")
evidence = agent.review(["src/api.py"])
print(evidence.status, [a.path for a in evidence.applied])
```

Every run returns an `EvidencePackage` (task contract, plan, edits, verification
results, critique, what was written) and is journaled to
`.smartcode/sessions.db` (LangGraph sqlite checkpointer) plus
`.smartcode/runs/*.jsonl`.

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
- **review**: retrieve → critic only; no writes, findings with severity.

Supported languages (tree-sitter grammars installed): Python, JavaScript,
TypeScript, Go, Rust, Java, C, C++, C#, Ruby, PHP — plus framework skill files
for React, FastAPI, Flask, Spring, Express. Other languages still work through
the generic path (bracket-balance check instead of AST).

## Providers

| id | backing | needs |
|----|---------|-------|
| `local` | Qwen2.5-1.5B-Instruct via transformers | `--extra local` (torch), model dir |
| `groq` | langchain-groq | `GROQ_API_KEY` |
| `anthropic` | langchain-anthropic | `ANTHROPIC_API_KEY` |
| `openai` | langchain-openai | `OPENAI_API_KEY` |
| `google` | langchain-google-genai | `GOOGLE_API_KEY` |
| `mock` | deterministic stub | nothing (offline/tests) |

Cloud providers use native structured output; the local SLM and mock use a
JSON-contract fallback with schema validation + bounded repair retries. For the
coder role, small models (`small_model = True`) skip JSON entirely and emit a
plain fenced code block that smartcode wraps into a structured edit itself —
1–2B models cannot reliably escape whole files inside JSON strings.

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
| Risk-tiered HITL write gate | `graph/nodes.py::hitl_gate` |
| Authority-Layered Context | `context/authority.py` |
| Context Contract | `context/contract.py` |
| Structured Scratchpad | `models.StructuredScratchpad`, updated by repair |
| Just-in-Time / Progressive Disclosure | `retrieval/tree_sitter.py`, `retrieval/repo_map.py` |
| Rerank-and-Budget + Sufficient Context Gate | `retrieval/context_budget.py` |
| Loss-Aware Compaction / Sliding Window | `context/compaction.py` |
| Skills & Procedural Memory | `skills/` (per-language/framework markdown) |
| Output Contract (schema-first) | `providers/base.py::invoke_structured` |

## Tests

```bash
uv run pytest            # tree-sitter symbols, AST sensor, mock end-to-end
```
