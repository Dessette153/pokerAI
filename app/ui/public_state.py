"""app/ui/public_state.py - State serialization helpers for UI.

The engine's GameState.to_dict() currently masks seat 1 by default (assuming
seat 0 is always the "hero" for UI). For Hero-vs-AI, we need seat-aware
masking without changing the engine.

These helpers:
- Return the same shape as GameState.to_dict()
- Mask the non-hero seat unless reveal_all=True or state.is_terminal
- Never include showdown hole cards in action_history payloads
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.engine.state import GameState


_MASK_CARD = {'rank': 0, 'suit': 0, 'str': '??'}


def _mask_hole_cards(hole_cards: List[List[dict]], hero_seat: int) -> List[List[dict]]:
    out: List[List[dict]] = []
    for i, hc in enumerate(hole_cards):
        if i != hero_seat:
            out.append([dict(_MASK_CARD), dict(_MASK_CARD)])
        else:
            out.append(hc)
    return out


def state_to_public_dict(state: GameState, hero_seat: int, reveal_all: bool = False) -> Dict[str, Any]:
    """Serialize `state` for a specific hero seat.

    `reveal_all=True` reveals both hole cards (typically only at showdown).
    """
    base = {
        'hand_id': state.hand_id,
        'street': state.street,
        'button_seat': state.button_seat,
        'to_act': state.to_act,
        'pot': round(state.pot, 2),
        'stacks': [round(s, 2) for s in state.stacks],
        'bb': state.bb,
        'sb': state.sb,
        'board': [c.to_dict() for c in state.board],
        'to_call': round(state.to_call, 2),
        'last_raise': round(state.last_raise, 2),
        'min_raise': round(state.min_raise, 2),
        'street_actions': list(state.street_actions),
        'is_terminal': state.is_terminal,
        'winner': state.winner,
        'pot_won': round(state.pot_won, 2) if state.pot_won is not None else None,
        'all_in': list(state.all_in),
    }

    hole = [[c.to_dict() for c in hc] for hc in state.hole_cards]
    if reveal_all or state.is_terminal:
        base['hole_cards'] = hole
    else:
        base['hole_cards'] = _mask_hole_cards(hole, hero_seat=hero_seat)

    # Avoid leaking showdown hole cards through action history; the UI gets
    # hole_cards via the dedicated field above.
    hist = []
    for a in state.action_history:
        if a.get('type') == 'showdown':
            a2 = dict(a)
            a2.pop('hole_cards', None)
            hist.append(a2)
        else:
            hist.append(a)
    base['action_history'] = hist

    return base
