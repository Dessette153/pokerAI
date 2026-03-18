"""app/agents/opponent_model.py

Lightweight opponent modeling for AI v2.

Tracks simple stats with smoothing/prior so early samples are stable:
- VPIP / PFR (preflop)
- aggression factor proxy (postflop)
- fold-to-cbet
- fold-to-raise

This model is intended to be updated incrementally from observed actions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

from app.engine.actions import ActionType


@dataclass
class _BetaStat:
    alpha: float = 1.0
    beta: float = 1.0

    def update(self, success: bool) -> None:
        if success:
            self.alpha += 1.0
        else:
            self.beta += 1.0

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)


@dataclass
class OpponentProfile:
    hands_observed: int = 0

    # Preflop stats
    vpip_hands: int = 0
    pfr_hands: int = 0

    # Postflop aggression proxy
    post_bets_raises: int = 0
    post_calls: int = 0

    # Responses
    fold_to_cbet: _BetaStat = field(default_factory=lambda: _BetaStat(alpha=2.0, beta=2.0))   # mild prior 50%
    fold_to_raise: _BetaStat = field(default_factory=lambda: _BetaStat(alpha=2.0, beta=2.0))  # mild prior 50%

    def snapshot(self):
        from app.agents.decision_context import OpponentProfileSnapshot
        vpip = self.vpip_hands / self.hands_observed if self.hands_observed else 0.0
        pfr = self.pfr_hands / self.hands_observed if self.hands_observed else 0.0
        aggression = (self.post_bets_raises + 1.0) / (self.post_calls + 1.0)
        return OpponentProfileSnapshot(
            hands=self.hands_observed,
            vpip=vpip,
            pfr=pfr,
            aggression=aggression,
            fold_to_cbet=self.fold_to_cbet.mean,
            fold_to_raise=self.fold_to_raise.mean,
        )


class OpponentModel:
    """Tracks villain tendencies from the hero's perspective."""

    def __init__(self, hero_seat: int):
        self.hero_seat = hero_seat
        self.villain_seat = 1 - hero_seat
        self.profile = OpponentProfile()

        self._current_hand_id: Optional[int] = None
        self._hand_seen_vpip = False
        self._hand_seen_pfr = False

        # Track whether hero made a cbet this hand/street, so we can count fold-to-cbet.
        self._pending_cbet_opportunity = False
        self._pending_raise_opportunity = False

    def on_new_hand(self, hand_id: int) -> None:
        self._current_hand_id = hand_id
        self.profile.hands_observed += 1
        self._hand_seen_vpip = False
        self._hand_seen_pfr = False
        self._pending_cbet_opportunity = False
        self._pending_raise_opportunity = False

    def observe_action(self, action_dict: Dict, street: str) -> None:
        """Observe a processed action record from `GameState.action_history`.

        action_dict keys come from engine.apply_action():
          player, type, amount, pot_before, ...
        """
        player = action_dict.get('player')
        a_type = action_dict.get('type')
        if not a_type:
            return

        # Normalize type to ActionType when possible.
        try:
            at = ActionType(a_type)
        except Exception:
            return

        is_preflop = (street == 'PREFLOP')

        if player == self.villain_seat:
            # VPIP: any voluntary money put in preflop beyond forced blinds.
            if is_preflop and not self._hand_seen_vpip and at in (ActionType.CALL, ActionType.RAISE, ActionType.ALL_IN):
                self.profile.vpip_hands += 1
                self._hand_seen_vpip = True

            # PFR: any raise/all-in preflop.
            if is_preflop and not self._hand_seen_pfr and at in (ActionType.RAISE, ActionType.ALL_IN):
                self.profile.pfr_hands += 1
                self._hand_seen_pfr = True

            # Aggression proxy postflop.
            if not is_preflop:
                if at in (ActionType.BET, ActionType.RAISE, ActionType.ALL_IN):
                    self.profile.post_bets_raises += 1
                elif at == ActionType.CALL:
                    self.profile.post_calls += 1

            # If villain faced hero c-bet and folded.
            if at == ActionType.FOLD and self._pending_cbet_opportunity:
                self.profile.fold_to_cbet.update(True)
                self._pending_cbet_opportunity = False

            # If villain faced hero raise and folded.
            if at == ActionType.FOLD and self._pending_raise_opportunity:
                self.profile.fold_to_raise.update(True)
                self._pending_raise_opportunity = False

            # If villain called instead of folding vs those opportunities.
            if at in (ActionType.CALL, ActionType.RAISE, ActionType.ALL_IN) and self._pending_cbet_opportunity:
                self.profile.fold_to_cbet.update(False)
                self._pending_cbet_opportunity = False

            if at in (ActionType.CALL, ActionType.RAISE, ActionType.ALL_IN) and self._pending_raise_opportunity:
                self.profile.fold_to_raise.update(False)
                self._pending_raise_opportunity = False

        elif player == self.hero_seat:
            # Track opportunities we are giving villain.
            if not is_preflop and at == ActionType.BET:
                # Treat first postflop bet by hero as c-bet opportunity for villain.
                self._pending_cbet_opportunity = True
            if at == ActionType.RAISE:
                self._pending_raise_opportunity = True
