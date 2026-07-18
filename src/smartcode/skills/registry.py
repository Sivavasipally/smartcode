"""Skills & Procedural Memory (Harness pattern #03).

Curated, versioned markdown guidance per language and framework, loaded only
when relevant (progressive disclosure: the skill is one context block, not a
prompt-embedded wall of rules). Files ship inside the package; users can add
overrides in ``.smartcode/skills/{languages,frameworks}/<name>.md``.
"""
from __future__ import annotations

from pathlib import Path

_PKG_DIR = Path(__file__).parent

#: framework id → language it implies (used for auto-detection sanity)
FRAMEWORK_LANGUAGE = {
    "react": "typescript",
    "fastapi": "python",
    "flask": "python",
    "spring": "java",
    "express": "javascript",
}


def _read(kind: str, name: str, user_dir: Path | None) -> str | None:
    name = name.lower().strip()
    if user_dir:
        override = user_dir / "skills" / kind / f"{name}.md"
        if override.is_file():
            return override.read_text(encoding="utf-8")
    packaged = _PKG_DIR / kind / f"{name}.md"
    if packaged.is_file():
        return packaged.read_text(encoding="utf-8")
    return None


def load_skill(language: str | None = None, framework: str | None = None,
               user_dir: Path | None = None) -> str:
    """Concatenate the applicable skill files (language first, then framework)."""
    parts: list[str] = []
    if language:
        text = _read("languages", language, user_dir)
        if text:
            parts.append(text.strip())
    if framework:
        text = _read("frameworks", framework, user_dir)
        if text:
            parts.append(text.strip())
    return "\n\n".join(parts)


def skill_for_task(language: str | None, framework: str | None,
                   data_dir: Path | None = None) -> str:
    if framework and not language:
        language = FRAMEWORK_LANGUAGE.get(framework.lower())
    return load_skill(language, framework, user_dir=data_dir)
