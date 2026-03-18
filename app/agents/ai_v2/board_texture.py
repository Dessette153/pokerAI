"""app/agents/board_texture.py

Lightweight board texture analysis used for AI v2 heuristics.

This is intentionally heuristic (not solver-accurate), but provides
stable, testable labels like dry/semi-wet/wet and features such as:
- paired boards
- monotone / two-tone
- connectedness (straight run)
"""

from __future__ import annotations

from collections import Counter
from typing import List

from app.engine.cards import Card
from .decision_context import BoardTexture


def _max_consecutive_run(ranks: List[int]) -> int:
    if not ranks:
        return 0
    ranks = sorted(set(ranks))

    # Handle wheel connectivity for A-5 only as a bonus on low boards.
    # We add "1" rank if there is an Ace.
    if 14 in ranks:
        ranks_with_wheel = set(ranks)
        ranks_with_wheel.add(1)
        ranks = sorted(ranks_with_wheel)

    best = 1
    cur = 1
    for i in range(1, len(ranks)):
        if ranks[i] == ranks[i - 1] + 1:
            cur += 1
            best = max(best, cur)
        else:
            cur = 1
    return best


def analyze_board(street: str, board: List[Card]) -> BoardTexture:
    """Analyze the current public board."""
    ranks = [c.rank for c in board]
    suits = [c.suit for c in board]

    rank_counts = Counter(ranks)
    suit_counts = Counter(suits)

    is_paired = any(v >= 2 for v in rank_counts.values())
    max_suit_count = max(suit_counts.values()) if suit_counts else 0

    is_monotone = (len(board) >= 3 and max_suit_count == len(board))
    is_two_tone = (len(board) >= 3 and len(suit_counts) == 2 and max_suit_count == len(board) - 1)

    straight_run = _max_consecutive_run(ranks)
    high_card = max(ranks) if ranks else 0
    unique_ranks = len(set(ranks))

    # Texture heuristic.
    wet_score = 0
    if is_monotone:
        wet_score += 3
    elif is_two_tone:
        wet_score += 2
    if straight_run >= 4:
        wet_score += 3
    elif straight_run == 3:
        wet_score += 2
    if is_paired:
        # Paired boards are often "drier" for draws, but create trips/boats.
        wet_score += 1

    if wet_score >= 5:
        texture = 'wet'
    elif wet_score >= 3:
        texture = 'semi_wet'
    else:
        texture = 'dry'

    return BoardTexture(
        street=street,
        texture=texture,
        is_paired=is_paired,
        is_monotone=is_monotone,
        is_two_tone=is_two_tone,
        max_suit_count=max_suit_count,
        straight_run=straight_run,
        high_card=high_card,
        unique_ranks=unique_ranks,
    )
