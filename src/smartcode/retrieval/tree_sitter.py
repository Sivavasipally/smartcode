"""Tree-sitter parsing for many languages (Just-in-Time / Progressive Disclosure).

This is the *deterministic sensor* + *retrieval* layer: parse a source file into an
AST and extract named symbols (functions, classes, methods, etc.) with byte ranges.
The coder node then loads *only* the relevant symbols into context instead of whole
files — the *Just-in-Time Context* and *Progressive Disclosure* patterns from the
Context-engineering reference.

tree-sitter 0.25 API: ``Parser(Language(<language_pkg>.language()))``.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from tree_sitter import Language, Node, Parser

from ..config import LANG_BY_EXT

# ---------------------------------------------------------------------------
# Grammar registry
# ---------------------------------------------------------------------------
# Map our language id -> (importable module name, symbol-query name tuple).
# The query names are the canonical tree-sitter node types that represent a
# "named declaration" for that language.
_LANGUAGE_MODULES: dict[str, str] = {
    "python": "tree_sitter_python",
    "javascript": "tree_sitter_javascript",
    "typescript": "tree_sitter_typescript",
    "go": "tree_sitter_go",
    "rust": "tree_sitter_rust",
    "java": "tree_sitter_java",
    "c": "tree_sitter_c",
    "cpp": "tree_sitter_cpp",
    "csharp": "tree_sitter_c_sharp",
    "ruby": "tree_sitter_ruby",
    "php": "tree_sitter_php",
}

# Node types that count as "named symbols" per language. Conservative + uniform.
_SYMBOL_NODE_TYPES: dict[str, tuple[str, ...]] = {
    "python": ("function_definition", "class_definition", "decorated_definition"),
    # NOTE: export_statement is deliberately absent — the walker must descend
    # through it to reach the real declaration inside.
    "javascript": ("function_declaration", "class_declaration", "method_definition"),
    "typescript": ("function_declaration", "class_declaration", "method_definition",
                   "interface_declaration", "type_alias_declaration"),
    "go": ("function_declaration", "method_declaration", "type_declaration"),
    "rust": ("function_item", "struct_item", "enum_item", "impl_item", "trait_item"),
    "java": ("method_declaration", "class_declaration", "interface_declaration",
             "constructor_declaration", "annotation_type_declaration"),
    "c": ("function_definition", "struct_specifier", "enum_specifier",
          "type_definition"),
    "cpp": ("function_definition", "class_specifier", "struct_specifier",
            "enum_specifier"),
    "csharp": ("method_declaration", "class_declaration", "interface_declaration",
               "struct_declaration", "enum_declaration"),
    "ruby": ("method", "class", "module"),
    "php": ("function_definition", "class_declaration", "method_declaration",
            "interface_declaration"),
}

# Some tree-sitter modules expose two languages (e.g. typescript exposes ts+tsx)
_LANGUAGE_FACTORY: dict[str, str] = {
    "typescript": "language_typescript",  # use the typescript (not tsx) factory
}


class GrammarError(RuntimeError):
    """Raised when a grammar module is missing or fails to load."""


@dataclass(frozen=True)
class _Loaded:
    language: Language
    parser: Parser
    symbol_types: tuple[str, ...]


_PARSERS: dict[str, _Loaded] = {}


def supported_languages() -> list[str]:
    """Return language ids for which a grammar *module* is importable."""
    out: list[str] = []
    for lang, mod in _LANGUAGE_MODULES.items():
        try:
            importlib.import_module(mod)
            out.append(lang)
        except Exception:
            continue
    return out


def _load(lang: str) -> _Loaded:
    if lang in _PARSERS:
        return _PARSERS[lang]
    mod_name = _LANGUAGE_MODULES.get(lang)
    if not mod_name:
        raise GrammarError(f"No grammar mapping for language {lang!r}")
    try:
        mod = importlib.import_module(mod_name)
    except Exception as e:  # pragma: no cover - import error is environment-specific
        raise GrammarError(
            f"Grammar module {mod_name!r} for {lang!r} is not installed: {e}. "
            f"Install it (e.g. `uv pip install tree_sitter_{lang}`) and retry."
        ) from e

    factory_name = _LANGUAGE_FACTORY.get(lang, "language")
    capsule = getattr(mod, factory_name, None) or getattr(mod, "language")
    try:
        language = Language(capsule())
        parser = Parser(language)
    except Exception as e:  # pragma: no cover
        raise GrammarError(f"Failed to initialise grammar for {lang!r}: {e}") from e

    loaded = _Loaded(language, parser, _SYMBOL_NODE_TYPES.get(lang, ()))
    _PARSERS[lang] = loaded
    return loaded


def language_for_file(path: str | Path) -> Optional[str]:
    """Return the language id for a file path from its extension, or None."""
    return LANG_BY_EXT.get(Path(path).suffix.lower())


# ---------------------------------------------------------------------------
# Symbol model
# ---------------------------------------------------------------------------
@dataclass
class Symbol:
    name: str
    kind: str
    start_line: int   # 1-based
    end_line: int     # 1-based
    start_byte: int
    end_byte: int
    body: str = ""

    def as_dict(self) -> dict:
        return {
            "name": self.name, "kind": self.kind,
            "start_line": self.start_line, "end_line": self.end_line,
        }


@dataclass
class ParseResult:
    path: str
    language: str
    ok: bool
    symbols: list[Symbol] = field(default_factory=list)
    error: str = ""
    n_lines: int = 0
    source: bytes = b""

    @property
    def names(self) -> list[str]:
        return [s.name for s in self.symbols]


def _node_name(node: Node, source: bytes) -> str:
    """Best-effort name extraction for a declaration node."""
    # The 'name' child is the convention across most tree-sitter grammars.
    for child in node.children:
        if child.type == "name":
            return source[child.start_byte:child.end_byte].decode("utf-8", "replace")
    # Some grammars put the identifier directly (e.g. go type_declaration).
    for child in node.children:
        if child.type == "identifier" or child.type.endswith("identifier"):
            return source[child.start_byte:child.end_byte].decode("utf-8", "replace")
    # Fall back to the first identifier-like token.
    ident = node.child_by_field_name("name")
    if ident is not None:
        return source[ident.start_byte:ident.end_byte].decode("utf-8", "replace")
    return node.type


def parse_source(source: str, lang: str, path: str = "<memory>") -> ParseResult:
    """Parse ``source`` as ``lang`` and return named symbols."""
    try:
        loaded = _load(lang)
    except GrammarError as e:
        return ParseResult(path=path, language=lang, ok=False, error=str(e))

    data = source.encode("utf-8")
    try:
        tree = loaded.parser.parse(data)
    except Exception as e:  # pragma: no cover
        return ParseResult(path=path, language=lang, ok=False, error=f"parse error: {e}")

    if tree.root_node is None or tree.root_node.has_error:
        # We still extract what symbols we can; has_error doesn't necessarily abort.
        pass

    symbols: list[Symbol] = []
    n_lines = source.count("\n") + 1

    def walk(node: Node) -> None:
        if node.type in loaded.symbol_types:
            name = _node_name(node, data)
            # For decorated definitions the real decl is one level down.
            if node.type == "decorated_definition":
                inner = next((c for c in node.children if c.type in loaded.symbol_types), node)
                name = _node_name(inner, data) or name
            symbols.append(
                Symbol(
                    name=name or node.type,
                    kind=node.type,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    start_byte=node.start_byte,
                    end_byte=node.end_byte,
                    body=data[node.start_byte:node.end_byte].decode("utf-8", "replace"),
                )
            )
            # Recurse into the body to capture nested methods (e.g. class -> methods),
            # but avoid duplicating: only descend into class-like containers.
            if node.type in ("class_definition", "class_declaration", "impl_item",
                             "class_specifier", "struct_specifier", "interface_declaration"):
                for child in node.children:
                    walk(child)
        else:
            for child in node.children:
                walk(child)

    walk(tree.root_node)
    return ParseResult(
        path=path, language=lang, ok=True, symbols=symbols,
        n_lines=n_lines, source=data,
    )


def parse_file(path: str | Path, lang: Optional[str] = None) -> ParseResult:
    """Parse a file from disk, inferring the language from the extension."""
    p = Path(path)
    if not p.exists():
        return ParseResult(path=str(p), language=lang or "unknown", ok=False,
                           error="file not found")
    resolved_lang = lang or language_for_file(p)
    if not resolved_lang:
        return ParseResult(path=str(p), language="unknown", ok=False,
                           error=f"no language mapping for extension {p.suffix!r}")
    try:
        source = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return ParseResult(path=str(p), language=resolved_lang, ok=False, error=str(e))
    return parse_source(source, resolved_lang, str(p))


def extract_symbols(source: str, lang: str) -> list[Symbol]:
    """Convenience wrapper returning just the symbol list."""
    return parse_source(source, lang).symbols


def fetch_symbol_bodies(result: ParseResult, names: Iterable[str]) -> str:
    """Return concatenated bodies for the requested symbols (progressive disclosure)."""
    want = set(names)
    parts = [s.body for s in result.symbols if s.name in want]
    return "\n\n".join(parts)


def bracket_balanced(source: str) -> bool:
    """Language-agnostic cheap structural check (paired brackets, ignoring strings)."""
    # Fast, conservative scanner: skip string/comment regions where reasonable.
    pairs = {"(": ")", "{": "}", "[": "]"}
    closing = set(pairs.values())
    stack: list[str] = []
    i, n = 0, len(source)
    in_str: Optional[str] = None
    while i < n:
        c = source[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == in_str:
                in_str = None
            i += 1
            continue
        if c in ('"', "'", "`"):
            in_str = c
        elif c in pairs:
            stack.append(c)
        elif c in closing:
            if not stack or pairs[stack.pop()] != c:
                return False
        i += 1
    return not stack
