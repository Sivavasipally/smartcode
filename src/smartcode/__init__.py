"""smartcode — local-first, multi-provider code-generation agent on LangGraph.

Public API::

    from smartcode import CodeAgent, generate, modify, review
"""
from .agent import CodeAgent, generate, modify, review
from .models import EvidencePackage, TaskContract

__version__ = "0.1.0"
__all__ = ["CodeAgent", "generate", "modify", "review", "EvidencePackage", "TaskContract"]
