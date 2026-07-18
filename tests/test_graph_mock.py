"""End-to-end graph runs with the deterministic mock provider."""
from pathlib import Path

import pytest

from smartcode.agent import CodeAgent
from smartcode.config import Settings


@pytest.fixture()
def agent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = Settings(
        provider="mock",
        run_linters=False,
        run_tests=False,
        enable_checkpointer=False,
        enable_hitl=False,
        data_dir=tmp_path / ".smartcode",
    )
    return CodeAgent(settings=settings)


def test_generate_new_python(agent, tmp_path):
    out = tmp_path / "out" / "solution.py"
    ev = agent.generate("a solve function", language="python", out_path=str(out))

    assert ev.status == "success"
    assert ev.plan is not None and ev.plan.steps
    assert ev.verify is not None and ev.verify.overall_ok
    assert ev.critique is not None and ev.critique.satisfies_acceptance
    assert out.exists()
    assert "def solve" in out.read_text(encoding="utf-8")
    assert ev.applied and ev.applied[0].applied


def test_modify_existing_file(agent, tmp_path):
    target = tmp_path / "mod_me.py"
    target.write_text("def old():\n    return 'old'\n", encoding="utf-8")

    ev = agent.modify([str(target)], "replace old with solve")

    assert ev.status == "success"
    text = target.read_text(encoding="utf-8")
    assert "def solve" in text
    assert "old" not in text  # whole-file replace by the mock coder


def test_review_reports_without_writing(agent, tmp_path):
    target = tmp_path / "review_me.py"
    original = "def f(x):\n    return x\n"
    target.write_text(original, encoding="utf-8")

    ev = agent.review([str(target)])

    assert ev.status == "review_only"
    assert ev.critique is not None
    assert target.read_text(encoding="utf-8") == original  # untouched
    assert not ev.applied


def test_modify_missing_file_fails_cleanly(agent, tmp_path):
    ev = agent.modify([str(tmp_path / "nope.py")], "change something")
    assert ev.status == "rejected"
    assert "error:" in ev.task.notes


def test_evidence_persisted(agent, tmp_path):
    agent.generate("anything", language="python",
                   out_path=str(tmp_path / "x.py"))
    runs = list((tmp_path / ".smartcode" / "runs").glob("evidence-*.json"))
    assert runs, "evidence package should be written to the run ledger"
