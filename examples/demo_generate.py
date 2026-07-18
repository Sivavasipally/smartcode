"""Generate a new Python module.

Run offline with the mock provider, or set provider="groq" / "anthropic" /
"google" / "local" for a real model:

    uv run python examples/demo_generate.py
"""
from smartcode import CodeAgent

agent = CodeAgent(provider="mock", enable_hitl=False, enable_checkpointer=False)
evidence = agent.generate(
    "a slugify(text) helper that lowercases, strips accents and joins words with '-'",
    language="python",
    out_path="examples/output/slug.py",
    acceptance=["handles unicode input", "no external dependencies"],
)

print("status:", evidence.status)
print("plan:", [s.description for s in evidence.plan.steps] if evidence.plan else None)
print("written:", [a.path for a in evidence.applied if a.applied])
