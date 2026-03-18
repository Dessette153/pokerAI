"""app/agents/range_updater.py

Heuristic updates to villain range weights based on observed actions.

This is intentionally lightweight: it does not attempt to solve equilibrium.
Instead it nudges a weighted range towards:
- stronger hands after aggressive preflop lines
- more polar ranges after large postflop bets
- looser ranges for passive/calling actions

The goal is to give AI v2 a better prior than "random hand".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List

from app.engine.actions import ActionType
from .range_model import WeightedRange


# Hand-type groups (very rough)
PREMIUM = {
    'AA', 'KK', 'QQ', 'JJ', 'AKs', 'AKo'
}
STRONG = {
    'TT', '99', 'AQs', 'AQo', 'AJs', 'ATs', 'KQs', 'KQo', 'KJs', 'QJs'
}
MEDIUM = {
    '88', '77', '66', '55', '44', '33', '22',
    'A9s', 'A8s', 'A7s', 'A6s', 'A5s', 'A4s', 'A3s', 'A2s',
    'KTs', 'QTs', 'JTs', 'T9s', '98s', '87s', '76s', '65s',
    'AJo', 'KJo', 'QJo'
}

# Everything else treated as "weak".


def _all_keys(r: WeightedRange) -> List[str]:
    return list(r.weights.keys())


def _weak_keys(r: WeightedRange) -> List[str]:
    strongish = set(PREMIUM) | set(STRONG) | set(MEDIUM)
    return [k for k in _all_keys(r) if k not in strongish]


@dataclass
class RangeUpdateConfig:
    preflop_raise_premium_mult: float = 2.8
    preflop_raise_strong_mult: float = 2.0
    preflop_raise_medium_mult: float = 1.1
    preflop_raise_weak_mult: float = 0.55

    preflop_call_premium_mult: float = 0.9
    preflop_call_strong_mult: float = 1.0
    preflop_call_medium_mult: float = 1.15
    preflop_call_weak_mult: float = 1.05

    post_large_bet_polar_mult: float = 1.25
    post_check_back_mult: float = 1.10


class RangeUpdater:
    def __init__(self, cfg: RangeUpdateConfig | None = None):
        self.cfg = cfg or RangeUpdateConfig()

    def on_new_hand(self, rng: WeightedRange) -> None:
        # mild normalization
        rng.normalized()

    def apply_observed_action(
        self,
        *,
        rng: WeightedRange,
        action_dict: Dict,
        street: str,
    ) -> WeightedRange:
        a_type = action_dict.get('type')
        if not a_type:
            return rng

        try:
            at = ActionType(a_type)
        except Exception:
            return rng

        # Determine sizing relative to pot when available.
        pot_before = float(action_dict.get('pot_before') or 0.0)
        amount = float(action_dict.get('amount') or 0.0)
        pot_frac = amount / pot_before if pot_before > 0 else 0.0

        if street == 'PREFLOP':
            if at in (ActionType.RAISE, ActionType.ALL_IN):
                rng.apply_multiplier(PREMIUM, self.cfg.preflop_raise_premium_mult)
                rng.apply_multiplier(STRONG, self.cfg.preflop_raise_strong_mult)
                rng.apply_multiplier(MEDIUM, self.cfg.preflop_raise_medium_mult)
                rng.apply_multiplier(_weak_keys(rng), self.cfg.preflop_raise_weak_mult)

            elif at == ActionType.CALL:
                rng.apply_multiplier(PREMIUM, self.cfg.preflop_call_premium_mult)
                rng.apply_multiplier(STRONG, self.cfg.preflop_call_strong_mult)
                rng.apply_multiplier(MEDIUM, self.cfg.preflop_call_medium_mult)
                rng.apply_multiplier(_weak_keys(rng), self.cfg.preflop_call_weak_mult)

        else:
            # Postflop heuristics:
            if at in (ActionType.BET, ActionType.RAISE, ActionType.ALL_IN):
                if pot_frac >= 0.75:
                    # Polarize: shift mass to stronger region (and a bit to weak bluff region).
                    rng.apply_multiplier(PREMIUM, 1.25)
                    rng.apply_multiplier(STRONG, 1.15)
                    rng.apply_multiplier(MEDIUM, 0.92)
                    rng.apply_multiplier(_weak_keys(rng), self.cfg.post_large_bet_polar_mult)
                else:
                    # Small/medium bet: slightly stronger.
                    rng.apply_multiplier(PREMIUM, 1.12)
                    rng.apply_multiplier(STRONG, 1.08)
                    rng.apply_multiplier(MEDIUM, 1.02)

            elif at == ActionType.CHECK:
                # Checking tends to contain more medium/weak hands.
                rng.apply_multiplier(MEDIUM, self.cfg.post_check_back_mult)
                rng.apply_multiplier(_weak_keys(rng), 1.08)
                rng.apply_multiplier(PREMIUM, 0.95)

            elif at == ActionType.CALL:
                # Calling keeps draws and medium strength.
                rng.apply_multiplier(MEDIUM, 1.08)
                rng.apply_multiplier(STRONG, 1.02)

            elif at == ActionType.FOLD:
                # Folding removes some of the weak region (conditional on this line).
                rng.apply_multiplier(_weak_keys(rng), 0.92)

        rng.normalized()
        return rng
