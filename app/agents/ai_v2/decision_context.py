"""app/agents/decision_context.py

Small, serializable context objects used by AI v2 for decision-making
and debugging/explanations.

Kept under agents/ to avoid coupling with engine/.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from app.engine.cards import Card


@dataclass(frozen=True)
class BoardTexture:
    street: str
    texture: str  # dry | semi_wet | wet
    is_paired: bool
    is_monotone: bool
    is_two_tone: bool
    max_suit_count: int
    straight_run: int
    high_card: int
    unique_ranks: int

    def to_dict(self) -> Dict:
        return {
            'street': self.street,
            'texture': self.texture,
            'is_paired': self.is_paired,
            'is_monotone': self.is_monotone,
            'is_two_tone': self.is_two_tone,
            'max_suit_count': self.max_suit_count,
            'straight_run': self.straight_run,
            'high_card': self.high_card,
            'unique_ranks': self.unique_ranks,
        }


@dataclass(frozen=True)
class OpponentProfileSnapshot:
    hands: int
    vpip: float
    pfr: float
    aggression: float
    fold_to_cbet: float
    fold_to_raise: float

    def to_dict(self) -> Dict:
        return {
            'hands': self.hands,
            'vpip': round(self.vpip, 4),
            'pfr': round(self.pfr, 4),
            'aggression': round(self.aggression, 4),
            'fold_to_cbet': round(self.fold_to_cbet, 4),
            'fold_to_raise': round(self.fold_to_raise, 4),
        }


@dataclass
class DecisionContext:
    hand_id: int
    street: str
    hero: int
    villain: int
    pot: float
    to_call: float
    hero_stack: float
    villain_stack: float
    spr: float
    is_ip_postflop: bool
    board: List[Card]
    hero_hole: List[Card]

    board_texture: BoardTexture
    opponent: OpponentProfileSnapshot

    # Computed estimates
    equity_vs_range: float = 0.5
    fold_equity: float = 0.0

    def to_expl(self) -> Dict:
        return {
            'hand_id': self.hand_id,
            'street': self.street,
            'position': 'IP' if self.is_ip_postflop else 'OOP',
            'spr': round(self.spr, 3),
            'board_texture': self.board_texture.to_dict(),
            'opponent': self.opponent.to_dict(),
            'equity_vs_range': round(self.equity_vs_range, 4),
            'fold_equity': round(self.fold_equity, 4),
        }
