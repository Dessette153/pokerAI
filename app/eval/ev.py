"""
app/eval/ev.py - Pot odds and Expected Value calculations
"""
from __future__ import annotations


def pot_odds(to_call: float, pot: float) -> float:
    """
    Pot odds: the equity needed to break-even on a call.
    pot_odds = to_call / (pot + to_call)
    """
    if to_call <= 0:
        return 0.0
    return to_call / (pot + to_call)


def call_ev(equity: float, pot: float, to_call: float) -> float:
    """
    EV of calling = equity * (pot + to_call) - (1 - equity) * to_call
    Simplified: equity * pot - (1 - equity) * to_call
    """
    if to_call <= 0:
        return 0.0
    return equity * pot - (1.0 - equity) * to_call


def bet_ev(equity: float, pot: float, bet_size: float, fold_equity: float = 0.3) -> float:
    """
    Simplified EV of betting.
    When villain folds (probability fold_equity): we win current pot.
    When villain calls (probability 1-fold_equity): equity * (pot + 2*bet) - bet.
    """
    ev_fold = fold_equity * pot
    ev_call = (1.0 - fold_equity) * (equity * (pot + 2 * bet_size) - bet_size)
    return ev_fold + ev_call


def raise_size_for_label(label: str, pot: float, bb: float) -> float:
    """
    Convert a bet size label into a chip amount.
    label: 'large' (75% pot), 'medium' (50% pot), 'small' (33% pot)
    Minimum is 1 BB.
    """
    fractions = {'large': 0.75, 'medium': 0.50, 'small': 0.33}
    frac = fractions.get(label, 0.50)
    return max(bb, round(pot * frac))
