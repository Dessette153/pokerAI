"""
app/eval/equity.py - Monte Carlo equity calculation
Time-bounded sampling with configurable min/max samples.
"""
from __future__ import annotations
import time
import random
from typing import List

from app.engine.cards import Card, Deck
from app.engine.evaluator import evaluate_hand, compare_hands


def monte_carlo_equity(
    hole_cards: List[Card],
    board: List[Card],
    num_players: int = 2,
    time_budget_ms: int = 900,
    min_samples: int = 2000,
    max_samples: int = 20000,
) -> float:
    """
    Estimate win probability for hole_cards via Monte Carlo simulation.

    Args:
        hole_cards: Our 2 hole cards
        board: Known community cards (0-5 cards)
        num_players: Always 2 for heads-up
        time_budget_ms: Max wall time in ms
        min_samples: Minimum number of simulations
        max_samples: Maximum number of simulations

    Returns:
        Win probability [0.0, 1.0] (ties count as 0.5)
    """
    known_cards = set(hole_cards) | set(board)
    cards_needed_on_board = 5 - len(board)

    # Build the remaining deck (exclude known cards)
    remaining = [
        Card(rank, suit)
        for rank in range(2, 15)
        for suit in range(4)
        if Card(rank, suit) not in known_cards
    ]

    wins = 0
    ties = 0
    total = 0
    deadline = time.time() + time_budget_ms / 1000.0

    while total < max_samples:
        if total >= min_samples and time.time() >= deadline:
            break

        # Shuffle remaining cards
        random.shuffle(remaining)
        idx = 0

        # Deal opponent hole cards
        opp_hole = remaining[idx:idx + 2]
        idx += 2

        # Complete the board
        run_board = list(board) + remaining[idx:idx + cards_needed_on_board]

        # Evaluate both hands
        my_score = evaluate_hand(hole_cards + run_board)
        opp_score = evaluate_hand(opp_hole + run_board)

        result = compare_hands(my_score, opp_score)
        if result == 1:
            wins += 1
        elif result == 0:
            ties += 1

        total += 1

    if total == 0:
        return 0.5

    return (wins + ties * 0.5) / total


def river_equity(
    hole_cards: List[Card],
    board: List[Card],
) -> float:
    """
    Exact equity on the river (board is complete: 5 cards).
    Enumerate all possible opponent hole card combinations.
    """
    assert len(board) == 5
    known = set(hole_cards) | set(board)
    remaining = [Card(r, s) for r in range(2, 15) for s in range(4) if Card(r, s) not in known]

    my_score = evaluate_hand(hole_cards + board)
    wins = 0
    ties = 0
    total = 0

    for i in range(len(remaining)):
        for j in range(i + 1, len(remaining)):
            opp = [remaining[i], remaining[j]]
            opp_score = evaluate_hand(opp + board)
            res = compare_hands(my_score, opp_score)
            if res == 1:
                wins += 1
            elif res == 0:
                ties += 1
            total += 1

    return (wins + ties * 0.5) / total if total > 0 else 0.5
