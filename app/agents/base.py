"""
app/agents/base.py - Abstract base class for all agents
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Tuple, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from app.engine.state import GameState
    from app.engine.actions import Action


class BaseAgent(ABC):
    def __init__(self, name: str = "Agent"):
        self.name = name

    @abstractmethod
    def select_action(self, state: 'GameState') -> Tuple['Action', Dict]:
        """
        Select an action given the current game state.

        Returns:
            (action, explanation) where explanation is a dict with
            keys like: equity, pot_odds, ev, size_label, tier, reasoning
        """
        ...

    def __str__(self) -> str:
        return self.name
