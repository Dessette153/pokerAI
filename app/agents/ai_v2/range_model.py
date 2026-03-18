"""app/agents/range_model.py

Simplified range representation and equity-vs-range estimation for AI v2.

We represent villain's range as weights over 169 hand *types* (AA, AKs, AKo ...).
For equity we sample actual 2-card combos consistent with the hand type and
current dead cards (hero hole + board).

This is a pragmatic middle ground: more realistic than "random hand" and much
faster than full range enumeration on every decision.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from app.engine.cards import Card
from app.engine.evaluator import evaluate_hand, compare_hands
from .hand_utils import all_hand_keys, generate_combos_for_key, filter_dead_combos


_ALL_KEYS = all_hand_keys()


def _build_combo_cache() -> Dict[str, List[Tuple[Card, Card]]]:
    cache: Dict[str, List[Tuple[Card, Card]]] = {}
    for k in _ALL_KEYS:
        cache[k] = generate_combos_for_key(k)
    return cache


_COMBO_CACHE = _build_combo_cache()


@dataclass
class WeightedRange:
    weights: Dict[str, float]

    @classmethod
    def uniform(cls) -> 'WeightedRange':
        w = {k: 1.0 for k in _ALL_KEYS}
        return cls(weights=w).normalized()

    def copy(self) -> 'WeightedRange':
        return WeightedRange(weights=dict(self.weights))

    def normalized(self) -> 'WeightedRange':
        total = sum(max(0.0, v) for v in self.weights.values())
        if total <= 0:
            return WeightedRange.uniform()
        self.weights = {k: max(0.0, v) / total for k, v in self.weights.items()}
        return self

    def apply_multiplier(self, keys: Iterable[str], mult: float) -> None:
        for k in keys:
            if k in self.weights:
                self.weights[k] *= mult

    def sample_hole(self, dead: Iterable[Card], rng: random.Random) -> Optional[List[Card]]:
        """Sample an opponent hole-card combo from the weighted range."""
        dead_set = set(dead)

        # Try a few times to avoid expensive filtering of all keys on every call.
        keys = list(self.weights.keys())
        probs = [self.weights[k] for k in keys]

        for _ in range(12):
            k = rng.choices(keys, weights=probs, k=1)[0]
            combos = _COMBO_CACHE.get(k) or []
            valid = filter_dead_combos(combos, dead_set)
            if valid:
                c1, c2 = rng.choice(valid)
                return [c1, c2]

        # Fallback: try any key that has valid combos.
        for k in keys:
            combos = _COMBO_CACHE.get(k) or []
            valid = filter_dead_combos(combos, dead_set)
            if valid:
                c1, c2 = rng.choice(valid)
                return [c1, c2]

        return None

    def key_mass(self, keys: Iterable[str]) -> float:
        return sum(self.weights.get(k, 0.0) for k in keys)

    def rough_hash(self) -> int:
        """Coarse hash for caching; not cryptographic."""
        # Bucket weights into 1% increments for stability.
        items = tuple(sorted((k, int(self.weights.get(k, 0.0) * 100)) for k in _ALL_KEYS))
        return hash(items)


def estimate_equity_vs_range(
    *,
    hero_hole: List[Card],
    board: List[Card],
    villain_range: WeightedRange,
    time_budget_ms: int,
    min_samples: int,
    max_samples: int,
    rng: random.Random,
) -> float:
    """Monte Carlo equity where villain hands are sampled from a weighted range."""
    dead = set(hero_hole) | set(board)
    cards_needed = 5 - len(board)

    # Remaining cards excluding known. Build once.
    base_remaining = [
        Card(rank, suit)
        for rank in range(2, 15)
        for suit in range(4)
        if Card(rank, suit) not in dead
    ]

    wins = 0
    ties = 0
    total = 0
    deadline = time.time() + time_budget_ms / 1000.0

    while total < max_samples:
        if total >= min_samples and time.time() >= deadline:
            break

        opp_hole = villain_range.sample_hole(dead, rng)
        if not opp_hole:
            # Should be extremely rare; fall back to uniform opponent hand.
            rng.shuffle(base_remaining)
            opp_hole = base_remaining[:2]

        opp_dead = set(opp_hole)
        rem = [c for c in base_remaining if c not in opp_dead]

        rng.shuffle(rem)
        run_board = list(board) + rem[:cards_needed]

        my_score = evaluate_hand(hero_hole + run_board)
        opp_score = evaluate_hand(opp_hole + run_board)
        res = compare_hands(my_score, opp_score)
        if res == 1:
            wins += 1
        elif res == 0:
            ties += 1

        total += 1

    if total == 0:
        return 0.5

    return (wins + ties * 0.5) / total
