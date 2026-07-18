"""Central configuration for smartcode.

All knobs are overridable via environment variables (prefix ``SMARTCODE_``) so the
agent is deployable without code changes. The defaults favour the local SLM and a
safe, auditable harness (Task-Contract + Plan-Execute-Verify + Evidence Package).
"""
from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# ---------------------------------------------------------------------------
# Known providers and the local model location
# ---------------------------------------------------------------------------
PROVIDERS = ("local", "groq", "anthropic", "openai", "google", "mock")

# Default model names per provider — override with SMARTCODE_<PROVIDER>_MODEL
DEFAULT_MODELS: dict[str, str] = {
    "local": "Qwen2.5-1.5B-Instruct",
    "groq": "llama-3.3-70b-versatile",
    "anthropic": "claude-sonnet-4-5",
    "openai": "gpt-4.1",
    "google": "gemini-2.0-flash",
    "mock": "mock",
}

# Tree-sitter language id by file extension (languages we ship grammars for)
LANG_BY_EXT: dict[str, str] = {
    ".py": "python", ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript",
    ".go": "go", ".rs": "rust", ".java": "java",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp",
    ".cs": "csharp", ".rb": "ruby", ".php": "php",
}


class Settings(BaseSettings):
    """Runtime settings, populated from env vars (``SMARTCODE_*``) or defaults."""

    model_config = SettingsConfigDict(
        env_prefix="SMARTCODE_", env_file=".env", env_file_encoding="utf-8",
        extra="ignore", case_sensitive=False,
    )

    # --- provider selection -------------------------------------------------
    provider: str = Field(default="local", description="active provider id")
    #: Cloud model overrides
    groq_model: str = DEFAULT_MODELS["groq"]
    anthropic_model: str = DEFAULT_MODELS["anthropic"]
    openai_model: str = DEFAULT_MODELS["openai"]
    google_model: str = DEFAULT_MODELS["google"]

    # --- local SLM ----------------------------------------------------------
    local_model_path: Path = Field(
        default=Path(r"D:/models/Qwen2.5-1.5B-Instruct"),
        description="path to the local Qwen2.5-1.5B-Instruct checkpoint",
    )
    local_device: str = Field(default="auto", description="'auto' | 'cuda' | 'cpu'")
    local_dtype: str = Field(default="auto", description="'auto' | 'fp16' | 'fp32' | 'bf16'")
    local_temperature: float = Field(default=0.2)
    local_max_new_tokens: int = Field(default=1024)

    # --- agent budgets & control loop --------------------------------------
    max_revisions: int = Field(default=3, ge=0, le=10,
                               description="max critic→repair loops before we accept best-effort")
    max_plan_steps: int = Field(default=6, ge=1, le=20)
    context_token_budget: int = Field(default=6000, ge=500,
                                      description="soft cap on retrieved context tokens")
    generation_timeout_s: int = Field(default=180, ge=10)

    # --- verification & risk ------------------------------------------------
    run_linters: bool = Field(default=True)
    run_tests: bool = Field(default=True)
    test_command: str | None = Field(
        default=None,
        description="explicit test command (e.g. 'pytest -q'); tests only run when set",
    )
    #: Risk tier gating for the write gate. 'low' = auto-apply; 'medium' = confirm;
    #: 'high' = require explicit approval. Files outside writable_roots are always blocked.
    default_risk_tier: str = Field(default="medium")
    writable_roots: list[Path] = Field(default_factory=list)

    # --- state / persistence ------------------------------------------------
    data_dir: Path = Field(default=Path(".smartcode"))
    enable_checkpointer: bool = Field(default=True)
    enable_hitl: bool = Field(default=True)

    # --- observability ------------------------------------------------------
    verbose: bool = Field(default=False)

    @field_validator("provider")
    @classmethod
    def _valid_provider(cls, v: str) -> str:
        v = v.lower()
        if v not in PROVIDERS:
            raise ValueError(f"provider must be one of {PROVIDERS}, got {v!r}")
        return v

    @field_validator("default_risk_tier")
    @classmethod
    def _valid_tier(cls, v: str) -> str:
        v = v.lower()
        if v not in ("low", "medium", "high"):
            raise ValueError("risk tier must be 'low' | 'medium' | 'high'")
        return v

    @property
    def model_name(self) -> str:
        """The model id for the active provider."""
        if self.provider in ("local", "mock"):
            return DEFAULT_MODELS[self.provider]
        return getattr(self, f"{self.provider}_model")

    @property
    def session_db_path(self) -> Path:
        return self.data_dir / "sessions.db"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)


def load_settings(**overrides: object) -> Settings:
    """Build a :class:`Settings`, applying keyword overrides on top of env/defaults."""
    # Export .env into the process environment: pydantic-settings only consumes
    # SMARTCODE_* fields from it, but provider API keys (GROQ_API_KEY, ...) must
    # reach os.environ for the availability checks and the langchain clients.
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    fields = Settings.model_fields
    clean = {k: v for k, v in overrides.items() if k in fields and v is not None}
    return Settings(**clean)
