"""Deterministic sensor + edit application."""
import pytest

from smartcode.editing import EditError, apply_edit_to_text, materialize
from smartcode.models import CodeEdit
from smartcode.verify.ast_checks import check_files

GOOD_PY = "def add(a: int, b: int) -> int:\n    return a + b\n"
BAD_PY = "def add(a, b)\n    return a + b\n"          # missing colon
GOOD_JS = "function add(a, b) {\n  return a + b;\n}\n"
BAD_JS = "function add(a, b) {\n  return a + b;\n"    # unbalanced brace


def test_sensor_passes_good_code():
    result = check_files({"m.py": GOOD_PY, "m.js": GOOD_JS})
    assert result.overall_ok
    assert result.all_passed


def test_sensor_rejects_bad_python():
    result = check_files({"m.py": BAD_PY})
    assert not result.overall_ok
    assert "py-compile" in result.summary or "parse" in result.summary


def test_sensor_rejects_bad_js():
    result = check_files({"m.js": BAD_JS})
    assert not result.overall_ok


def test_sensor_rejects_empty():
    result = check_files({"m.py": "   \n"})
    assert not result.overall_ok


# --- edit application ------------------------------------------------------
ORIGINAL = (
    "def one():\n    return 1\n\n"
    "def two():\n    return 2\n\n"
    "def three():\n    return 3\n"
)


def test_replace_symbol_anchor():
    edit = CodeEdit(action="replace", path="m.py", anchor="two",
                    content="def two():\n    return 22\n")
    out = apply_edit_to_text(ORIGINAL, edit)
    assert "return 22" in out
    assert "return 1" in out and "return 3" in out
    assert "return 2\n" not in out.replace("return 22", "")


def test_replace_line_range():
    edit = CodeEdit(action="replace", path="m.py", anchor="1-2",
                    content="def one():\n    return 100\n")
    out = apply_edit_to_text(ORIGINAL, edit)
    assert "return 100" in out and "return 2" in out


def test_insert_after_symbol():
    edit = CodeEdit(action="insert", path="m.py", anchor="one",
                    content="\ndef one_b():\n    return 0\n")
    out = apply_edit_to_text(ORIGINAL, edit)
    assert out.index("one_b") < out.index("def two")


def test_delete_symbol():
    edit = CodeEdit(action="delete", path="m.py", anchor="three", content="")
    out = apply_edit_to_text(ORIGINAL, edit)
    assert "three" not in out


def test_whole_file_replace_and_create():
    rep = CodeEdit(action="replace", path="m.py", anchor=None, content="x = 1\n")
    assert apply_edit_to_text(ORIGINAL, rep) == "x = 1\n"
    cre = CodeEdit(action="create", path="new.py", content="y = 2")
    assert apply_edit_to_text("", cre) == "y = 2\n"


def test_bad_anchor_raises():
    edit = CodeEdit(action="replace", path="m.py", anchor="does_not_exist_zz",
                    content="pass\n")
    with pytest.raises(EditError):
        apply_edit_to_text(ORIGINAL, edit)


def test_materialize_missing_file_rejected(tmp_path):
    edit = CodeEdit(action="replace", path=str(tmp_path / "ghost.py"),
                    anchor=None, content="pass\n")
    with pytest.raises(EditError):
        materialize([edit])


# --- code-fence fallback extraction ---------------------------------------
def test_extract_code_fence():
    from smartcode.providers.base import extract_code_fence

    fenced = "Here you go:\n```python\ndef f():\n    return 1\n```\nhope it helps"
    assert extract_code_fence(fenced) == "def f():\n    return 1\n"

    two = "```py\nx = 1\n```\n```py\ndef bigger():\n    return 2\n```"
    assert "bigger" in extract_code_fence(two)

    bare = "def g():\n    return 3"
    assert extract_code_fence(bare) == "def g():\n    return 3\n"

    assert extract_code_fence("Sorry, I cannot help with that.") is None


# --- unified diffs ---------------------------------------------------------
def test_unified_diffs(tmp_path):
    from smartcode.editing import unified_diffs

    existing = tmp_path / "old.py"
    existing.write_text("def f():\n    return 1\n", encoding="utf-8")
    files = {
        str(existing): "def f():\n    return 2\n",
        str(tmp_path / "new.py"): "x = 1\n",
    }
    diffs = unified_diffs(files)
    assert "-    return 1" in diffs[str(existing)]
    assert "+    return 2" in diffs[str(existing)]
    assert "+x = 1" in diffs[str(tmp_path / "new.py")]
