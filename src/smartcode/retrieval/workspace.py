"""Workspace-scale discovery: many repos under one root.

Deterministic layer that makes folder-scale runs safe:
- discover sub-repos (any dir with a vcs/manifest marker),
- index source files (language, symbols) with hard caps,
- rank candidate files against the objective (lexical, identifier-aware),
- render a budgeted workspace map for the target-selector LLM.

The LLM never invents the universe of files — it chooses from this index, and
its choices are re-validated against it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..config import LANG_BY_EXT
from .context_budget import _words  # identifier-aware tokenizer
from .tree_sitter import parse_file

_SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__",
    "dist", "build", "target", ".smartcode", ".idea", ".vscode", ".tox",
    ".pytest-tmp", "egg-info", "coverage", ".next", ".cache", "vendor",
}
_REPO_MARKERS = (
    ".git", "pyproject.toml", "package.json", "go.mod", "Cargo.toml",
    "pom.xml", "build.gradle", "Gemfile", "composer.json", ".sln",
)
_MAX_FILES_PER_REPO = 400
_MAX_TOTAL_FILES = 1200
_MAX_FILE_BYTES = 512_000


@dataclass
class SourceFile:
    path: Path            # absolute
    rel: str              # relative to workspace root, forward slashes
    repo: str
    language: str
    n_lines: int = 0
    symbols: list[str] = field(default_factory=list)
    score: float = 0.0


@dataclass
class RepoInfo:
    name: str
    path: Path
    markers: list[str] = field(default_factory=list)
    files: list[SourceFile] = field(default_factory=list)

    @property
    def languages(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for f in self.files:
            out[f.language] = out.get(f.language, 0) + 1
        return out


@dataclass
class WorkspaceIndex:
    root: Path
    repos: list[RepoInfo] = field(default_factory=list)
    truncated: bool = False

    @property
    def all_files(self) -> list[SourceFile]:
        return [f for r in self.repos for f in r.files]

    def has_file(self, rel_or_abs: str | Path) -> bool:
        p = Path(rel_or_abs)
        if not p.is_absolute():
            p = self.root / p
        try:
            rp = p.resolve()
        except OSError:
            return False
        return any(f.path == rp for f in self.all_files) or rp.is_file()

    def contains(self, rel_or_abs: str | Path) -> bool:
        """Is the path inside the workspace root (existing or not)?"""
        p = Path(rel_or_abs)
        if not p.is_absolute():
            p = self.root / p
        try:
            rp = p.resolve()
        except OSError:
            return False
        root = self.root.resolve()
        return rp == root or root in rp.parents


def _iter_dirs(root: Path):
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            entries = sorted(d.iterdir())
        except OSError:
            continue
        yield d, entries
        for p in entries:
            if p.is_dir() and p.name not in _SKIP_DIRS and not p.name.startswith("."):
                stack.append(p)


def discover_repos(root: Path) -> list[RepoInfo]:
    """Top-level dirs with a repo marker become repos; loose source under the
    root itself becomes the pseudo-repo "." — nothing is silently ignored."""
    root = root.resolve()
    repos: list[RepoInfo] = []

    for child in sorted(root.iterdir()) if root.is_dir() else []:
        if not child.is_dir() or child.name in _SKIP_DIRS or child.name.startswith("."):
            continue
        markers = [m for m in _REPO_MARKERS if (child / m).exists()]
        if markers:
            repos.append(RepoInfo(name=child.name, path=child, markers=markers))

    # The root itself is a pseudo-repo when it has markers or loose source;
    # build_index skips claimed sub-repo dirs when scanning it.
    root_markers = [m for m in _REPO_MARKERS if (root / m).exists()]
    if root_markers or not repos:
        repos.insert(0, RepoInfo(name=".", path=root, markers=root_markers))
    return repos


def build_index(root: str | Path) -> WorkspaceIndex:
    """Scan the workspace: repos → source files → (lazy) symbols."""
    root = Path(root).resolve()
    index = WorkspaceIndex(root=root)
    index.repos = discover_repos(root)
    claimed = {r.path for r in index.repos if r.path != root}

    total = 0
    for repo in index.repos:
        count = 0
        for d, entries in _iter_dirs(repo.path):
            if repo.path == root and any(c == d or c in d.parents for c in claimed):
                continue  # the root pseudo-repo must not re-scan sub-repos
            for p in entries:
                if not p.is_file():
                    continue
                lang = LANG_BY_EXT.get(p.suffix.lower())
                if not lang:
                    continue
                try:
                    if p.stat().st_size > _MAX_FILE_BYTES:
                        continue
                except OSError:
                    continue
                repo.files.append(SourceFile(
                    path=p.resolve(),
                    rel=p.resolve().relative_to(root).as_posix(),
                    repo=repo.name, language=lang,
                ))
                count += 1
                total += 1
                if count >= _MAX_FILES_PER_REPO or total >= _MAX_TOTAL_FILES:
                    index.truncated = True
                    break
            if count >= _MAX_FILES_PER_REPO or total >= _MAX_TOTAL_FILES:
                break
        if total >= _MAX_TOTAL_FILES:
            break
    return index


def rank_candidates(index: WorkspaceIndex, objective: str,
                    top_n: int = 40) -> list[SourceFile]:
    """Lexical relevance of every file to the objective. Symbols are parsed
    only for the provisional top slice (progressive disclosure — parsing 1200
    files would be wasted work)."""
    goal = _words(objective)

    for f in index.all_files:
        path_hits = len(goal & _words(f.rel))
        f.score = path_hits * 2.0

    provisional = sorted(index.all_files, key=lambda f: f.score, reverse=True)
    slice_ = provisional[: top_n * 3]
    for f in slice_:
        if not f.symbols:
            parsed = parse_file(f.path)
            if parsed.ok:
                f.symbols = [s.name for s in parsed.symbols][:30]
                f.n_lines = parsed.n_lines
        sym_hits = len(goal & _words(" ".join(f.symbols)))
        f.score += sym_hits * 3.0

    ranked = sorted(slice_, key=lambda f: f.score, reverse=True)[:top_n]
    return [f for f in ranked if f.score > 0] or ranked[: min(top_n, 15)]


def render_workspace_map(index: WorkspaceIndex, candidates: list[SourceFile],
                         max_other_files: int = 150) -> str:
    """Budgeted map: full symbol detail for candidates, path-only for the rest."""
    lines = [f"# Workspace: {index.root}  ({len(index.repos)} repo(s)"
             + (", truncated scan" if index.truncated else "") + ")"]
    cand_rels = {c.rel for c in candidates}

    for repo in index.repos:
        langs = ", ".join(f"{k}:{v}" for k, v in sorted(repo.languages.items()))
        lines.append(f"\n## repo {repo.name}  [{langs or 'no source files'}]"
                     + (f"  markers: {', '.join(repo.markers)}" if repo.markers else ""))
        listed = 0
        for f in repo.files:
            if f.rel in cand_rels:
                syms = ", ".join(f.symbols[:20])
                lines.append(f"- {f.rel} ({f.language}"
                             + (f", {f.n_lines} lines" if f.n_lines else "")
                             + (f"): {syms}" if syms else ")"))
            elif listed < max_other_files:
                lines.append(f"- {f.rel}")
                listed += 1
        if len(repo.files) > listed + len([c for c in candidates if c.repo == repo.name]):
            lines.append(f"- … more files elided")
    return "\n".join(lines)
