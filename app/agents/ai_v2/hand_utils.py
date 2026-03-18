"""app/agents/hand_utils.py

Shared utilities for representing hands/ranges in AI v2.

We intentionally do not import private helpers from `ai_v1.py` to keep
AI v1 untouched and preserve backward compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from app.engine.cards import Card


RANK_TO_CHAR: Dict[int, str] = {14: 'A', 13: 'K', 12: 'Q', 11: 'J', 10: 'T',
                               9: '9', 8: '8', 7: '7', 6: '6', 5: '5', 4: '4', 3: '3', 2: '2'}
CHAR_TO_RANK: Dict[str, int] = {v: k for k, v in RANK_TO_CHAR.items()}


def hand_key(cards: Sequence[Card]) -> str:
    """Convert 2 hole cards to a canonical key: AA, AKs, AKo, T9s."""
    c1, c2 = sorted(cards, key=lambda c: c.rank, reverse=True)
    r1 = RANK_TO_CHAR[c1.rank]
    r2 = RANK_TO_CHAR[c2.rank]
    if c1.rank == c2.rank:
        return f"{r1}{r2}"
    suited = 's' if c1.suit == c2.suit else 'o'
    return f"{r1}{r2}{suited}"


def parse_hand_key(key: str) -> Tuple[int, int, Optional[str]]:
    """Return (high_rank, low_rank, suitedness) where suitedness in {s,o,None for pairs}."""
    key = key.strip()
    if len(key) == 2:
        r = CHAR_TO_RANK[key[0].upper()]
        return r, r, None
    if len(key) == 3:
        r1 = CHAR_TO_RANK[key[0].upper()]
        r2 = CHAR_TO_RANK[key[1].upper()]
        suited = key[2].lower()
        return r1, r2, suited
    raise ValueError(f"Invalid hand key: {key}")


def all_hand_keys() -> List[str]:
    """All 169 canonical hand keys."""
    ranks = list(range(14, 1, -1))
    keys: List[str] = []
    for i, r1 in enumerate(ranks):
        for r2 in ranks[i:]:
            if r1 == r2:
                keys.append(f"{RANK_TO_CHAR[r1]}{RANK_TO_CHAR[r2]}")
            else:
                keys.append(f"{RANK_TO_CHAR[r1]}{RANK_TO_CHAR[r2]}s")
                keys.append(f"{RANK_TO_CHAR[r1]}{RANK_TO_CHAR[r2]}o")
    return keys


def generate_combos_for_key(key: str) -> List[Tuple[Card, Card]]:
    """Generate all 2-card combos matching a hand key (ignoring dead cards)."""
    r1, r2, suited = parse_hand_key(key)

    combos: List[Tuple[Card, Card]] = []
    suits = [0, 1, 2, 3]

    if suited is None:
        # Pair: choose 2 suits out of 4.
        for i in range(4):
            for j in range(i + 1, 4):
                combos.append((Card(r1, suits[i]), Card(r2, suits[j])))
        return combos

    if suited == 's':
        for s in suits:
            combos.append((Card(r1, s), Card(r2, s)))
        return combos

    if suited == 'o':
        for s1 in suits:
            for s2 in suits:
                if s1 == s2:
                    continue
                combos.append((Card(r1, s1), Card(r2, s2)))
        return combos

    raise ValueError(f"Invalid suitedness in key: {key}")


def filter_dead_combos(
    combos: Iterable[Tuple[Card, Card]],
    dead: Iterable[Card],
) -> List[Tuple[Card, Card]]:
    dead_set = set(dead)
    out: List[Tuple[Card, Card]] = []
    for c1, c2 in combos:
        if c1 in dead_set or c2 in dead_set:
            continue
        if c1 == c2:
            continue
        out.append((c1, c2))
    return out
