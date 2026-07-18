"""Symbol extraction across languages (retrieval layer)."""
from smartcode.retrieval.tree_sitter import (
    bracket_balanced,
    language_for_file,
    parse_source,
    supported_languages,
)

PY = '''
class UserService:
    def get_user(self, uid):
        return uid

def top_level(x):
    return x * 2
'''

TS = '''
export interface User { id: number; }

export function getUser(id: number): User {
  return { id };
}

class Repo {
  find(id: number) { return id; }
}
'''

GO = '''
package main

type Server struct{}

func (s *Server) Handle() {}

func main() {}
'''


def test_python_symbols():
    result = parse_source(PY, "python")
    assert result.ok
    names = result.names
    assert "UserService" in names
    assert "get_user" in names       # nested method found via class descent
    assert "top_level" in names


def test_typescript_symbols():
    result = parse_source(TS, "typescript")
    assert result.ok
    assert any("getUser" in n or "User" in n for n in result.names)
    assert result.symbols  # at least the class/function declarations


def test_go_symbols():
    result = parse_source(GO, "go")
    assert result.ok
    assert "main" in result.names
    assert any("Handle" in n or "Server" in n for n in result.names)


def test_language_for_file():
    assert language_for_file("a/b/x.py") == "python"
    assert language_for_file("x.tsx") == "typescript"
    assert language_for_file("x.rs") == "rust"
    assert language_for_file("x.unknown") is None


def test_supported_languages_cover_core():
    langs = set(supported_languages())
    assert {"python", "javascript", "typescript", "go", "rust", "java"} <= langs


def test_bracket_balanced():
    assert bracket_balanced("f(a, [1, 2], {k: 'v(}'})")
    assert not bracket_balanced("f(a, [1, 2}")
