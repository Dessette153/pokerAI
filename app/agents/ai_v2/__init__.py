"""AI v2 package.

Re-exports the main agent class for convenient imports:

  from app.agents.ai_v2 import AIV2Agent

This keeps compatibility even if the implementation lives in submodules.
"""

from .ai_v2 import AIV2Agent

__all__ = ["AIV2Agent"]
