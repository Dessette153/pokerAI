"""app/agents/sizing_policy.py

Sizing buckets for AI v2: small / medium / large.

Maps to chip amounts compatible with the engine:
- For BET: amount is bet_size
- For RAISE: amount is raise_size above call

We keep a simple mapping to avoid adding new engine constraints.
"""

from __future__ import annotations

from dataclasses import dataclass

from .decision_context import BoardTexture


@dataclass(frozen=True)
class SizeChoice:
    label: str
    pot_fraction: float


def choose_size_bucket(
    *,
    intent: str,  # value | bluff | semi
    texture: BoardTexture,
    spr: float,
    is_ip_postflop: bool,
) -> SizeChoice:
    # Defaults per intent
    if intent == 'value':
        frac = 0.66
        if texture.texture == 'wet':
            frac = 0.85
        elif texture.texture == 'dry':
            frac = 0.55
    elif intent == 'bluff':
        frac = 0.33
        if texture.texture == 'wet':
            frac = 0.55
    else:  # semi
        frac = 0.55
        if texture.texture == 'wet':
            frac = 0.75

    # Lower SPR -> larger geometric sizing.
    if spr <= 2.5:
        frac = max(frac, 0.85)
    elif spr <= 4.0:
        frac = max(frac, 0.66)

    # OOP: prefer larger bets for protection, smaller for bluffs.
    if not is_ip_postflop and intent == 'value':
        frac = min(1.0, frac + 0.10)
    if not is_ip_postflop and intent == 'bluff':
        frac = max(0.25, frac - 0.05)

    label = 'medium'
    if frac <= 0.40:
        label = 'small'
    elif frac >= 0.78:
        label = 'large'

    return SizeChoice(label=label, pot_fraction=frac)


def sizing_amount(
    *,
    pot: float,
    bb: float,
    min_raise: float,
    stack: float,
    to_call: float,
    pot_fraction: float,
) -> float:
    """Return a raise_size (above call) to target a pot fraction."""
    if pot <= 0:
        target = bb
    else:
        target = round(pot * pot_fraction)
        target = max(target, bb)

    # Ensure legal minimum raise.
    raise_size = max(float(target), float(min_raise))

    # Cap by remaining stack beyond call.
    max_raise = max(0.0, stack - to_call)
    raise_size = min(raise_size, max_raise)

    # Never negative.
    return max(0.0, raise_size)
