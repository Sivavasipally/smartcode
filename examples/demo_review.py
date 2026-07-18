"""Review a file — findings only, nothing is written (offline mock demo)."""
from pathlib import Path

from smartcode import CodeAgent

target = Path("examples/output/review_me.py")
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(
    "import os\n\n"
    "def load(path):\n"
    "    data = open(path).read()\n"
    "    exec(data)\n"
    "    return data\n",
    encoding="utf-8",
)

agent = CodeAgent(provider="mock", enable_checkpointer=False)
evidence = agent.review([str(target)], focus="security issues")

print("status:", evidence.status)
if evidence.critique:
    print("score:", evidence.critique.score)
    for f in evidence.critique.findings:
        print(f"- [{f.severity}] {f.message}")
