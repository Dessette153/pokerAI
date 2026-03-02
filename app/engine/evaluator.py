"""
app/engine/evaluator.py - Custom Texas Hold'em hand evaluator
No external dependencies. Evaluates 5-7 cards to a numeric score.
"""
from __future__ import annotations
from itertools import combinations
from enum import IntEnum
from typing import List, Tuple

from app.engine.cards import Card


class HandRank(IntEnum):
    HIGH_CARD = 1
    ONE_PAIR = 2
    TWO_PAIR = 3
    THREE_OF_A_KIND = 4
    STRAIGHT = 5
    FLUSH = 6
    FULL_HOUSE = 7
    FOUR_OF_A_KIND = 8
    STRAIGHT_FLUSH = 9
    ROYAL_FLUSH = 10


HAND_RANK_NAMES = {
    HandRank.HIGH_CARD: "High Card",
    HandRank.ONE_PAIR: "One Pair",
    HandRank.TWO_PAIR: "Two Pair",
    HandRank.THREE_OF_A_KIND: "Three of a Kind",
    HandRank.STRAIGHT: "Straight",
    HandRank.FLUSH: "Flush",
    HandRank.FULL_HOUSE: "Full House",
    HandRank.FOUR_OF_A_KIND: "Four of a Kind",
    HandRank.STRAIGHT_FLUSH: "Straight Flush",
    HandRank.ROYAL_FLUSH: "Royal Flush",
}


def _ranks_to_score(sorted_ranks: List[int]) -> int:
    """Convert a sorted (desc) list of up to 5 rank values into a tiebreaker score."""
    score = 0
    for r in sorted_ranks:
        score = score * 15 + r
    return score


def _is_flush(cards: List[Card]) -> bool:
    return len({c.suit for c in cards}) == 1


def _is_straight(ranks: List[int]) -> Tuple[bool, int]:
    """
    Returns (is_straight, high_card_rank).
    Handles A-low straight (A-2-3-4-5).
    ranks should be sorted desc, unique.
    """
    unique = sorted(set(ranks), reverse=True)
    if len(unique) < 5:
        return False, 0
    # Normal straight
    for i in range(len(unique) - 4):
        window = unique[i:i+5]
        if window[0] - window[4] == 4:
            return True, window[0]
    # Wheel: A-2-3-4-5
    if set([14, 2, 3, 4, 5]).issubset(set(unique)):
        return True, 5
    return False, 0


def _eval_5(cards: List[Card]) -> int:
    """
    Evaluate exactly 5 cards and return a numeric score.
    Higher score = better hand.
    Score layout: category * 15^5 * 10 + tiebreaker
    """
    assert len(cards) == 5
    ranks = sorted([c.rank for c in cards], reverse=True)
    flush = _is_flush(cards)
    is_str, str_high = _is_straight(ranks)

    from collections import Counter
    rank_counts = Counter(ranks)
    count_groups = sorted(rank_counts.items(), key=lambda x: (x[1], x[0]), reverse=True)
    # count_groups: [(rank, count), ...] sorted by count desc then rank desc

    counts = [cg[1] for cg in count_groups]
    top_ranks = [cg[0] for cg in count_groups]

    if flush and is_str:
        if str_high == 14:
            cat = HandRank.ROYAL_FLUSH
        else:
            cat = HandRank.STRAIGHT_FLUSH
        tb = str_high
    elif counts[0] == 4:
        cat = HandRank.FOUR_OF_A_KIND
        # four-of-a-kind rank first, kicker second
        tb = _ranks_to_score(top_ranks[:2])
    elif counts[0] == 3 and counts[1] == 2:
        cat = HandRank.FULL_HOUSE
        tb = _ranks_to_score(top_ranks[:2])
    elif flush:
        cat = HandRank.FLUSH
        tb = _ranks_to_score(ranks)
    elif is_str:
        cat = HandRank.STRAIGHT
        tb = str_high
    elif counts[0] == 3:
        cat = HandRank.THREE_OF_A_KIND
        tb = _ranks_to_score(top_ranks)
    elif counts[0] == 2 and counts[1] == 2:
        cat = HandRank.TWO_PAIR
        tb = _ranks_to_score(top_ranks)
    elif counts[0] == 2:
        cat = HandRank.ONE_PAIR
        tb = _ranks_to_score(top_ranks)
    else:
        cat = HandRank.HIGH_CARD
        tb = _ranks_to_score(ranks)

    base = 15 ** 5 * 10
    return int(cat) * base + tb


def evaluate_hand(cards: List[Card]) -> int:
    """
    Evaluate 5-7 cards. Returns best possible 5-card score.
    """
    if len(cards) == 5:
        return _eval_5(cards)
    best = 0
    for combo in combinations(cards, 5):
        score = _eval_5(list(combo))
        if score > best:
            best = score
    return best


def hand_rank_name(score: int) -> str:
    """Return hand category name from score."""
    base = 15 ** 5 * 10
    cat = score // base
    return HAND_RANK_NAMES.get(HandRank(cat), "Unknown")


def compare_hands(score_a: int, score_b: int) -> int:
    """
    Returns:
      1  if a wins
     -1  if b wins
      0  if tie
    """
    if score_a > score_b:
        return 1
    if score_b > score_a:
        return -1
    return 0
