"""Workspace-scale runs: discovery, ranking, and the proposal-gated pipeline."""
from pathlib import Path

import pytest

from smartcode.agent import CodeAgent
from smartcode.config import Settings
from smartcode.retrieval.workspace import build_index, rank_candidates


@pytest.fixture()
def workspace(tmp_path):
    """Two repos + loose root files, multiple languages."""
    a = tmp_path / "auth-service"
    (a / "src").mkdir(parents=True)
    (a / "pyproject.toml").write_text("[project]\nname='auth'\n", encoding="utf-8")
    (a / "src" / "login.py").write_text(
        "def login(user, password):\n    return True\n\n"
        "def validate_password(pw):\n    return len(pw) > 3\n",
        encoding="utf-8")
    (a / "src" / "billing.py").write_text(
        "def charge(amount):\n    return amount\n", encoding="utf-8")

    b = tmp_path / "web-app"
    (b / "lib").mkdir(parents=True)
    (b / "package.json").write_text("{}", encoding="utf-8")
    (b / "lib" / "cart.js").write_text(
        "function addToCart(item) {\n  return item;\n}\n", encoding="utf-8")
    return tmp_path


def test_discovery_finds_both_repos(workspace):
    index = build_index(workspace)
    names = {r.name for r in index.repos if r.files}
    assert "auth-service" in names
    assert "web-app" in names
    rels = {f.rel for f in index.all_files}
    assert "auth-service/src/login.py" in rels
    assert "web-app/lib/cart.js" in rels


def test_ranking_prefers_relevant_file(workspace):
    index = build_index(workspace)
    ranked = rank_candidates(index, "harden login password validation in auth")
    assert ranked, "expected candidates"
    assert ranked[0].rel == "auth-service/src/login.py"
    assert "validate_password" in ranked[0].symbols


def test_workspace_run_with_proposal_gate(workspace, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = Settings(provider="mock", run_linters=False, run_tests=False,
                       enable_checkpointer=False, enable_hitl=False,
                       data_dir=tmp_path / ".smartcode")
    seen = {}

    def proposal_cb(task, proposal, round_no):
        seen["targets"] = [(t.path, t.action) for t in proposal.targets]
        seen["round"] = round_no
        return {"decision": "approve"}

    agent = CodeAgent(settings=settings, proposal_callback=proposal_cb)
    ev = agent.workspace("harden login password validation in auth",
                         root=workspace)

    assert seen["targets"] == [("auth-service/src/login.py", "modify")]
    assert seen["round"] == 1
    assert ev.status == "success"
    text = (workspace / "auth-service/src/login.py").read_text(encoding="utf-8")
    assert "def solve" in text  # mock coder whole-file replace


def test_workspace_run_rejected_writes_nothing(workspace, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = Settings(provider="mock", run_linters=False, run_tests=False,
                       enable_checkpointer=False, enable_hitl=False,
                       data_dir=tmp_path / ".smartcode")
    original = (workspace / "auth-service/src/login.py").read_text(encoding="utf-8")

    agent = CodeAgent(settings=settings,
                      proposal_callback=lambda *a: {"decision": "reject",
                                                    "feedback": "wrong files"})
    ev = agent.workspace("harden login password validation", root=workspace)

    assert ev.status == "rejected"
    assert (workspace / "auth-service/src/login.py").read_text(encoding="utf-8") == original


def test_workspace_revise_loops_with_feedback(workspace, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = Settings(provider="mock", run_linters=False, run_tests=False,
                       enable_checkpointer=False, enable_hitl=False,
                       data_dir=tmp_path / ".smartcode")
    rounds = []

    def proposal_cb(task, proposal, round_no):
        rounds.append(round_no)
        return {"decision": "revise", "feedback": "look again"} if round_no == 1 \
            else {"decision": "approve"}

    agent = CodeAgent(settings=settings, proposal_callback=proposal_cb)
    ev = agent.workspace("harden login password validation", root=workspace)

    assert rounds == [1, 2]
    assert ev.status == "success"


def test_generate_proposes_output_location(workspace, tmp_path, monkeypatch):
    """gen without out_path: the agent proposes folder + filename from the
    codebase and creates the file there after approval."""
    monkeypatch.chdir(tmp_path)
    settings = Settings(provider="mock", run_linters=False, run_tests=False,
                       enable_checkpointer=False, enable_hitl=False,
                       data_dir=tmp_path / ".smartcode")
    seen = {}

    def proposal_cb(task, proposal, round_no):
        seen["targets"] = [(t.path, t.action) for t in proposal.targets]
        return {"decision": "approve"}

    agent = CodeAgent(settings=settings, proposal_callback=proposal_cb)
    ev = agent.generate("login validation helpers for auth", root=workspace,
                        language="python")

    assert ev.status == "success"
    (path, action), = seen["targets"]
    assert action == "create"
    assert path.startswith("auth-service/src/")   # conventional placement
    created = workspace / path
    assert created.exists()
    assert "def solve" in created.read_text(encoding="utf-8")
