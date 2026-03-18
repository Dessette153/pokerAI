"""app/agents/fold_equity.py

Fold equity estimation for AI v2.

This is a fast heuristic model (not a solver). It uses:
- bet size relative to pot
- board texture
- street
- opponent profile (overfolders vs stations)

Outputs a probability in [0,1].
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .decision_context import BoardTexture, OpponentProfileSnapshot


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def estimate_fold_equity(
    *,
    opponent: OpponentProfileSnapshot,
    texture: BoardTexture,
    street: str,
    pot: float,
    bet_size: float,
    is_raise: bool,
) -> float:
    """Estimate villain fold probability vs our bet/raise."""
    if pot <= 0 or bet_size <= 0:
        return 0.0

    pot_frac = bet_size / max(1.0, pot)

    # Baselines by street.
    street_bias = {
        'PREFLOP': -0.6,
        'FLOP': 0.2,
        'TURN': 0.1,
        'RIVER': 0.0,
    }.get(street, 0.1)

    # Texture: wet boards encourage calling with draws; dry boards fold more.
    texture_bias = {
        'dry': 0.35,
        'semi_wet': 0.10,
        'wet': -0.10,
    }.get(texture.texture, 0.10)

    # Raise tends to fold more than bet (but vs maniacs less so).
    raise_bias = 0.25 if is_raise else 0.0

    # Opponent tendencies (already smoothed):
    # - fold_to_cbet: influences flop/turn
    # - fold_to_raise: influences raise folds
    overfolder = (opponent.fold_to_cbet - 0.5) * 1.2
    raise_overfolder = (opponent.fold_to_raise - 0.5) * 1.0

    # Calling stations reduce FE; use VPIP as a weak proxy.
    station_penalty = max(0.0, opponent.vpip - 0.45) * 1.5

    # Pot fraction effect: bigger bets -> more folds.
    # Use log-ish growth so huge bets don't explode FE.
    size_term = 1.7 * math.log(1.0 + 1.8 * pot_frac)

    x = street_bias + texture_bias + raise_bias + size_term + overfolder + (raise_overfolder if is_raise else 0.0) - station_penalty

    fe = _sigmoid(x)
    # Clamp away from 0/1 extremes.
    return max(0.01, min(0.95, fe))
