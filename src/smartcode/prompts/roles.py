"""Role prompts (planner / coder / critic / classifier).

Each role gets: the authority-layered system prompt (policy → contract → skill
→ retrieved → scratchpad) plus a role-specific human message that restates the
output contract in prose. The machine-enforceable contract itself lives in
``invoke_structured`` (pydantic schema), so the prompt only has to steer, not
guarantee. Templates are jinja2 for readability.
"""
from __future__ import annotations

from jinja2 import Environment

from ..models import Plan, TaskContract

_env = Environment(trim_blocks=True, lstrip_blocks=True)

# ---------------------------------------------------------------------------
_CLASSIFIER = _env.from_string("""\
Classify the user's request into exactly one intent:
- "new": create code that does not exist yet
- "modify": change, update, extend, refactor or fix existing code
- "review": inspect existing code and report findings without changing it

Request: {{ objective }}
{% if targets %}Existing target files mentioned: {{ targets }}{% endif %}
""")


def render_classifier(objective: str, targets: list[str]) -> str:
    return _CLASSIFIER.render(objective=objective, targets=", ".join(targets))


# ---------------------------------------------------------------------------
_PLANNER = _env.from_string("""\
You are the PLANNER. Produce a short, executable plan for the objective.

Rules:
- At most {{ max_steps }} steps; each step is one bounded, verifiable change.
- For modify tasks, anchor steps to the symbols/files shown in the repo map
  and retrieved context — never invent files.
- Put anything you cannot resolve from the given context into open_questions
  instead of guessing.
- Keep the approach summary to 2-3 sentences.

Objective: {{ objective }}
Intent: {{ intent }}
""")


def render_planner(task: TaskContract, max_steps: int) -> str:
    return _PLANNER.render(objective=task.objective, intent=task.intent,
                           max_steps=max_steps)


# ---------------------------------------------------------------------------
_CODER = _env.from_string("""\
You are the CODER. Execute the plan by emitting structured edits.

LANGUAGE: {{ language }}
TARGET_FILES: {{ targets }}
intent: {{ intent }}

Plan:
{{ plan }}

Edit contract:
- action "create": new file; "content" is the complete file.
- action "replace": anchor is a symbol name (e.g. "UserService" or "get_user")
  or a line range "12-18"; empty anchor replaces the whole file. "content" is
  the complete replacement for the anchored region.
- action "insert": content is inserted after the anchored symbol/line
  (empty anchor appends at end of file).
- action "delete": removes the anchored region; content must be "".
- Paths must be inside the writable paths from the task contract.
- Emit complete, runnable code — all imports, no placeholders, no "...".
- Prefer the smallest set of edits that satisfies the acceptance criteria.
{% if feedback %}

Previous attempt failed verification/review. Fix these issues:
{{ feedback }}
{% endif %}
""")


def render_coder(task: TaskContract, plan: Plan, feedback: str = "") -> str:
    plan_txt = plan.approach + "\n" + "\n".join(
        f"{i}. {s.description}" + (f"  [{s.target}]" if s.target else "")
        for i, s in enumerate(plan.steps, 1)
    )
    return _CODER.render(
        language=task.language or "infer",
        targets=", ".join(str(p) for p in task.writable_paths) or "(choose a sensible path)",
        intent=task.intent,
        plan=plan_txt.strip(),
        feedback=feedback.strip(),
    )


# ---------------------------------------------------------------------------
_CRITIC = _env.from_string("""\
You are the CRITIC — an exacting code reviewer acting as the acceptance judge.

Acceptance criteria:
{% for a in acceptance %}- {{ a }}
{% endfor %}

Deterministic verification result: {{ verify_summary }}

{% if review_only %}
Mode: REVIEW ONLY. Report findings on the retrieved code; do not request revisions
(set revise=false). Score reflects current code quality.
{% else %}
Judge the proposed edits below. Set revise=true ONLY if a concrete, fixable
defect prevents the acceptance criteria from being met; describe each defect as
a finding with a severity and, where possible, a suggestion.
Score: 1.0 = production ready, 0.0 = unusable.

Proposed edits:
{{ edits }}
{% endif %}
""")


def render_critic(task: TaskContract, edits_text: str, verify_summary: str,
                  review_only: bool = False) -> str:
    return _CRITIC.render(
        acceptance=task.acceptance or ["fulfils the stated objective"],
        verify_summary=verify_summary or "not run",
        edits=edits_text,
        review_only=review_only,
    )
