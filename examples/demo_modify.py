"""Modify an existing TypeScript file (offline mock demo).

Swap provider="mock" for "groq"/"anthropic"/"google"/"local" to do real work.
"""
from pathlib import Path

from smartcode import CodeAgent

target = Path("examples/output/api.ts")
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(
    "export function getUser(id: number) {\n  return { id };\n}\n",
    encoding="utf-8",
)

agent = CodeAgent(provider="mock", enable_hitl=False, enable_checkpointer=False)
evidence = agent.modify(
    [str(target)],
    "add an in-memory cache so repeated getUser calls reuse the same object",
    language="typescript",
)

print("status:", evidence.status)
print(target.read_text(encoding="utf-8"))
