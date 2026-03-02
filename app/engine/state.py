"""
app/engine/state.py - GameState and StreetSnapshot dataclasses
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
import copy

from app.engine.cards import Card


@dataclass
class GameState:
    hand_id: int
    street: str                      # PREFLOP / FLOP / TURN / RIVER
    button_seat: int                 # 0 or 1 (button = dealer = SB in heads-up)
    to_act: int                      # 0 or 1
    pot: float
    stacks: List[float]              # [player0_stack, player1_stack]
    bb: float
    sb: float
    board: List[Card]                # community cards revealed so far
    hole_cards: List[List[Card]]     # [[p0_c1,p0_c2],[p1_c1,p1_c2]]
    to_call: float                   # amount current player needs to call
    last_raise: float                # size of last raise (for min-raise calc)
    min_raise: float                 # minimum raise amount
    action_history: List[Dict]       # all actions this hand
    street_actions: List[Dict]       # actions in current street only
    # Tracks whether each player has voluntarily acted this street
    # Handles BB option in preflop cleanly
    voluntary_acted: List[bool] = field(default_factory=lambda: [False, False])
    is_terminal: bool = False
    winner: Optional[int] = None     # 0 or 1 (or -1 for split)
    pot_won: Optional[float] = None
    all_in: List[bool] = field(default_factory=lambda: [False, False])
    street_invested: List[float] = field(default_factory=lambda: [0.0, 0.0])
    total_invested: List[float] = field(default_factory=lambda: [0.0, 0.0])

    def copy(self) -> 'GameState':
        return copy.deepcopy(self)

    def to_dict(self, reveal_all: bool = False) -> Dict[str, Any]:
        """Serialize to JSON-safe dict."""
        hole = []
        for i, hc in enumerate(self.hole_cards):
            if not reveal_all and not self.is_terminal:
                # Always reveal player 0 (AI v1), mask opponent
                if i == 1:
                    hole.append([{'rank': 0, 'suit': 0, 'str': '??'},
                                  {'rank': 0, 'suit': 0, 'str': '??'}])
                    continue
            hole.append([c.to_dict() for c in hc])
        return {
            'hand_id': self.hand_id,
            'street': self.street,
            'button_seat': self.button_seat,
            'to_act': self.to_act,
            'pot': round(self.pot, 2),
            'stacks': [round(s, 2) for s in self.stacks],
            'bb': self.bb,
            'sb': self.sb,
            'board': [c.to_dict() for c in self.board],
            'hole_cards': hole,
            'to_call': round(self.to_call, 2),
            'last_raise': round(self.last_raise, 2),
            'min_raise': round(self.min_raise, 2),
            'action_history': list(self.action_history),
            'street_actions': list(self.street_actions),
            'is_terminal': self.is_terminal,
            'winner': self.winner,
            'pot_won': round(self.pot_won, 2) if self.pot_won is not None else None,
            'all_in': list(self.all_in),
        }


@dataclass
class StreetSnapshot:
    """Records all information about a single betting street for replay/revert."""
    street: str
    board_at_start: List[Card]
    stacks_at_start: List[float]
    pot_at_start: float
    actions: List[Dict]
    state_at_start: GameState        # deep copy at start of street
    state_at_end: Optional[GameState] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'street': self.street,
            'board_at_start': [c.to_dict() for c in self.board_at_start],
            'stacks_at_start': list(self.stacks_at_start),
            'pot_at_start': self.pot_at_start,
            'actions': list(self.actions),
            'state_at_start': self.state_at_start.to_dict(reveal_all=True),
            'state_at_end': self.state_at_end.to_dict(reveal_all=True) if self.state_at_end else None,
        }


@dataclass
class HandResult:
    hand_id: int
    winner: int                      # 0 or 1 (-1 = split)
    pot_won: float
    was_fold: bool
    fold_by: Optional[int]
    net_chips: List[float]           # net change [p0, p1]
    snapshots: List[StreetSnapshot]
    final_state: GameState
    showdown_scores: Optional[List[int]] = None
