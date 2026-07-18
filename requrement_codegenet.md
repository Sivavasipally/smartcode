pyproject.toml              # uv-managed, entry point smartcode=...; package = smartcode

README.md                   # what it is, install, provider keys, examples, pattern map

.env.example                # GROQ\_API\_KEY, ANTHROPIC\_API\_KEY, GOOGLE\_API\_KEY, OPENAI\_API\_KEY, SMARTCODE\_\*

src/smartcode/

&#x20; \_\_init\_\_.py               # public API: CodeAgent, generate, modify, review

&#x20; \_\_main\_\_.py               # python -m smartcode  → cli

&#x20; config.py                 # pydantic-settings: provider, model names, paths, budgets, risk tiers

&#x20; models.py                 # pydantic: Intent, TaskContract, Plan, Step, CodeEdit, VerifyResult, Critique, Evidence

&#x20; agent.py                  # CodeAgent facade: .generate/.modify/.review, async + sync, checkpointer wiring

&#x20; cli.py                    # Rich CLI: gen | modify | review | providers | doctor (rich tables/panels, streaming)

&#x20; providers/                # base, registry, local\_qwen, groq, anthropic, openai, google, mock

&#x20; context/

&#x20;   authority.py            # authority-layered system prompt builder (policy→org→app→task→retrieved→user)

&#x20;   contract.py             # ContextContract: required/forbidden/sufficiency/output schema

&#x20;   scratchpad.py           # StructuredScratchpad: goal/observations/decisions/open\_questions (JSON in state)

&#x20;   compaction.py           # loss-aware history compaction + sliding recency window

&#x20; retrieval/

&#x20;   tree\_sitter.py          # parse file → symbols/scopes per language (20 grammars installed)

&#x20;   repo\_map.py             # progressive disclosure: directory/symbol map, load on demand

&#x20;   context\_budget.py       # retrieve→dedupe→rerank→budget (sufficient-context gate)

&#x20; skills/                   # procedural memory: registry + per-language/framework markdown skill files

&#x20;   registry.py

&#x20;   languages/{python,typescript,javascript,go,rust,java,csharp,ruby,php,cpp}.md

&#x20;   frameworks/{react,fastapi,flask,spring,express}.md

&#x20; verify/

&#x20;   ast\_checks.py           # deterministic sensor: parse OK, balanced braces/brackets, import resolution

&#x20;   linters.py              # best-effort: ruff/py\_compile, eslint --parse, tsc --noEmit, gofmt -l, cargo check

&#x20;   tests.py                # run configured test command if present, capture pass/fail

&#x20;   runner.py               # sandboxed subprocess exec with timeout + risk-tier gating

&#x20; prompts/

&#x20;   system.py, planner.py, coder.py, critic.py  # jinja2 templates, output contracts per role

&#x20; graph/

&#x20;   state.py                # State TypedDict (+ reducer fields for scratchpad/evidence/edits)

&#x20;   nodes.py                # classify\_intent, planner, retriever, coder, verifier, critic, repair, hitl\_gate, finalize

&#x20;   supervisor.py           # routing logic (intent → path), risk-tier policy

&#x20;   builder.py              # build\_graph(checkpointer) → compiled StateGraph

&#x20;   checkpointer.py         # sqlite saver at .smartcode/sessions.db (durable ledger)

&#x20; observability.py          # structured run logger + rich callback handler (per-node trace)

examples/

&#x20; demo\_generate.py          # generate a Python module

&#x20; demo\_modify.py            # modify an existing TS file

&#x20; demo\_review.py            # review code

tests/

&#x20; test\_tree\_sitter.py       # symbol extraction across languages

&#x20; test\_verify.py            # AST sensor on good/bad snippets

&#x20; test\_graph\_mock.py        # end-to-end with mock provider (new + modify paths)

