"""
app/engine/actions.py - ActionType enum, Action dataclass, and legal action validation
"""
from __future__ import annotations
from enum import Enum
from dataclasses import dataclass
from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    from app.engine.state import GameState


class ActionType(Enum):
    FOLD = "fold"
    CHECK = "check"
    CALL = "call"
    BET = "bet"
    RAISE = "raise"


@dataclass
class Action:
    type: ActionType
    amount: float = 0.0   # Total chips to put in (for bet/raise: size above call)
    player: int = 0
    explanation: dict = None  # AI decision explanation

    def __post_init__(self):
        if self.explanation is None:
            self.explanation = {}

    def to_dict(self) -> dict:
        return {
            'type': self.type.value,
            'amount': self.amount,
            'player': self.player,
            'explanation': self.explanation,
        }


def legal_actions(state: 'GameState') -> List[ActionType]:
    """Return list of legal ActionTypes given the current game state."""
    if state.is_terminal:
        return []

    player = state.to_act
    stack = state.stacks[player]
    to_call = state.to_call
    actions = []

    if to_call > 0:
        # Can fold
        actions.append(ActionType.FOLD)
        # Can call (or go all-in for less)
        actions.append(ActionType.CALL)
        # Can raise if player has chips beyond the call
        if stack > to_call and not all(state.all_in):
            actions.append(ActionType.RAISE)
    else:
        # No bet to face
        actions.append(ActionType.CHECK)
        # Can bet if has chips
        if stack > 0 and not all(state.all_in):
            actions.append(ActionType.BET)

    return actions


def is_legal(action: Action, state: 'GameState') -> bool:
    return action.type in legal_actions(state)
