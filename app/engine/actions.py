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
    ALL_IN = "all_in"


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
    opponent = 1 - player
    stack = state.stacks[player]
    to_call = state.to_call
    actions = []

    if to_call > 0:
        # Can fold
        actions.append(ActionType.FOLD)
        # Can call (or go all-in for less)
        actions.append(ActionType.CALL)
        # If opponent is already all-in, raising is not meaningful/allowed.
        if not state.all_in[opponent] and not any(state.all_in):
            # Can raise if player has chips beyond the call
            if stack > to_call:
                actions.append(ActionType.RAISE)
            # Can go all-in (as a raise-all-in)
            if stack > 0 and not state.all_in[player]:
                actions.append(ActionType.ALL_IN)
    else:
        # No bet to face
        actions.append(ActionType.CHECK)
        # If anyone is all-in, there is no betting.
        if not any(state.all_in):
            # Can bet if has chips
            if stack > 0:
                actions.append(ActionType.BET)
            # Can go all-in if not already all-in
            if stack > 0 and not state.all_in[player]:
                actions.append(ActionType.ALL_IN)

    return actions


def is_legal(action: Action, state: 'GameState') -> bool:
    return action.type in legal_actions(state)
