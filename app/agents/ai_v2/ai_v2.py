"""app/agents/ai_v2.py - AI v2: Range-aware + FE-aware + exploitative agent.

Goals vs AI v1:
- Use a (simplified) opponent range model instead of assuming uniform random.
- Integrate fold equity into bet/raise EV.
- Adjust frequencies/sizing using board texture, position and SPR.
- Adapt to opponent tendencies (VPIP/PFR/aggression/fold stats).

This is intentionally heuristic and fast; it should remain runnable in the
existing simulator/UI without changing engine interfaces.
"""

from __future__ import annotations

import random
from typing import Dict, List, Tuple

import config
from app.agents.base import BaseAgent

from .board_texture import analyze_board
from .decision_context import DecisionContext
from .fold_equity import estimate_fold_equity
from .hand_utils import hand_key
from .opponent_model import OpponentModel
from .range_model import WeightedRange, estimate_equity_vs_range
from .range_updater import RangeUpdater, PREMIUM, STRONG, MEDIUM
from .sizing_policy import choose_size_bucket, sizing_amount
from app.engine.actions import Action, ActionType, legal_actions
from app.engine.state import GameState
from app.eval.ev import pot_odds, call_ev


class AIV2Agent(BaseAgent):
    def __init__(self, name: str = "AI v2", seat: int = 0, rng_seed: int | None = 7):
        super().__init__(name)
        self.seat = seat
        self.rng = random.Random(rng_seed)

        self.opp_model = OpponentModel(hero_seat=seat)
        self.range_updater = RangeUpdater()
        self.villain_range: WeightedRange = WeightedRange.uniform()

        self._last_hand_id: int | None = None
        self._last_hist_idx: int = 0
        self._hist_street: str = 'PREFLOP'

        # Simple cache for equity computations within a hand.
        self._eq_cache: Dict[tuple, float] = {}

    def _reset_for_new_hand(self, hand_id: int) -> None:
        self._last_hand_id = hand_id
        self._last_hist_idx = 0
        self._hist_street = 'PREFLOP'
        self._eq_cache = {}

        self.opp_model.on_new_hand(hand_id)

        # Initialize a prior range from opponent profile.
        snap = self.opp_model.profile.snapshot()
        self.villain_range = self._prior_range_from_profile(snap)
        self.range_updater.on_new_hand(self.villain_range)

    def _prior_range_from_profile(self, opp_snap) -> WeightedRange:
        r = WeightedRange.uniform()

        # VPIP-driven looseness.
        vpip = opp_snap.vpip
        if vpip <= 0.25:
            # Tight
            r.apply_multiplier(PREMIUM, 2.2)
            r.apply_multiplier(STRONG, 1.6)
            r.apply_multiplier(MEDIUM, 0.85)
        elif vpip >= 0.55:
            # Loose
            r.apply_multiplier(PREMIUM, 0.85)
            r.apply_multiplier(STRONG, 0.95)
            r.apply_multiplier(MEDIUM, 1.15)

        # PFR: higher PFR shifts range strength up.
        pfr = opp_snap.pfr
        if pfr >= 0.35:
            r.apply_multiplier(PREMIUM, 1.15)
            r.apply_multiplier(STRONG, 1.10)
        elif pfr <= 0.12:
            r.apply_multiplier(MEDIUM, 1.05)

        return r.normalized()

    def _process_new_history(self, state: GameState, hero: int, villain: int) -> None:
        # Walk action_history incrementally and update opponent model + range.
        # action_history includes "deal_board" entries that carry street transitions.
        for i in range(self._last_hist_idx, len(state.action_history)):
            entry = state.action_history[i]
            if entry.get('type') == 'deal_board':
                self._hist_street = entry.get('street') or self._hist_street
                continue

            street = self._hist_street
            self.opp_model.observe_action(entry, street)

            if entry.get('player') == villain:
                self.villain_range = self.range_updater.apply_observed_action(
                    rng=self.villain_range,
                    action_dict=entry,
                    street=street,
                )

        self._last_hist_idx = len(state.action_history)

    def _equity_vs_range(self, hero_hole, board) -> float:
        # Cache key is coarse: board+hero+range hash.
        key = (
            tuple(sorted((str(c) for c in hero_hole))),
            tuple(str(c) for c in board),
            self.villain_range.rough_hash(),
        )
        if key in self._eq_cache:
            return self._eq_cache[key]

        # Keep this cheaper than AI v1's single-hand equity calc.
        budget_ms = max(30, min(250, int(config.MC_TIME_BUDGET_MS * 0.35)))
        min_samples = max(250, int(budget_ms * 6))
        max_samples = max(1200, int(budget_ms * 25))

        eq = estimate_equity_vs_range(
            hero_hole=hero_hole,
            board=board,
            villain_range=self.villain_range,
            time_budget_ms=budget_ms,
            min_samples=min_samples,
            max_samples=max_samples,
            rng=self.rng,
        )
        self._eq_cache[key] = eq
        return eq

    @staticmethod
    def _aggressive_ev(*, equity: float, pot: float, to_call: float, raise_size: float, fe: float) -> float:
        # Profit if villain folds is +pot (see derivation in analysis).
        ev_fold = fe * pot

        # If called:
        invested = to_call + raise_size
        pot_if_called = pot + to_call + 2.0 * raise_size
        ev_called = equity * pot_if_called - (1.0 - equity) * invested

        return ev_fold + (1.0 - fe) * ev_called

    def select_action(self, state: GameState) -> Tuple[Action, Dict]:
        player = state.to_act
        hero = player
        villain = 1 - hero

        if self._last_hand_id != state.hand_id:
            self._reset_for_new_hand(state.hand_id)

        # Keep models updated from new action history.
        self._process_new_history(state, hero=hero, villain=villain)

        actions = legal_actions(state)
        my_hole = state.hole_cards[hero]

        texture = analyze_board(state.street, state.board)
        opp_snap = self.opp_model.profile.snapshot()

        eff_stack = min(state.stacks[hero], state.stacks[villain])
        spr = eff_stack / state.pot if state.pot > 0 else 99.0
        is_ip_postflop = (hero == state.button_seat and state.street != 'PREFLOP')

        ctx = DecisionContext(
            hand_id=state.hand_id,
            street=state.street,
            hero=hero,
            villain=villain,
            pot=state.pot,
            to_call=state.to_call,
            hero_stack=state.stacks[hero],
            villain_stack=state.stacks[villain],
            spr=spr,
            is_ip_postflop=is_ip_postflop,
            board=list(state.board),
            hero_hole=list(my_hole),
            board_texture=texture,
            opponent=opp_snap,
        )

        equity = self._equity_vs_range(my_hole, state.board)
        ctx.equity_vs_range = equity

        expl: Dict = ctx.to_expl()
        expl['hero_hand'] = hand_key(my_hole)
        expl['pot_odds'] = round(pot_odds(state.to_call, state.pot), 4) if state.to_call > 0 else 0.0

        # ---- Facing a bet ----
        if state.to_call > 0:
            odds = pot_odds(state.to_call, state.pot)

            # Aggro opponents have more bluffs -> call wider.
            aggro = max(0.0, opp_snap.aggression - 1.0)
            call_margin = config.MARGIN - min(0.02, aggro * 0.01)

            best_action = None
            best_ev = float('-inf')

            # Fold EV is 0
            if ActionType.FOLD in actions:
                best_action = Action(ActionType.FOLD, 0.0, hero)
                best_ev = 0.0

            # Call
            if ActionType.CALL in actions:
                cev = call_ev(equity, state.pot, state.to_call)
                if equity >= odds - call_margin or cev > 0:
                    if cev > best_ev:
                        best_action = Action(ActionType.CALL, state.to_call, hero)
                        best_ev = cev

            # Raise / jam
            if ActionType.RAISE in actions or ActionType.ALL_IN in actions:
                # Only consider raising when we have strong equity or good FE.
                intent = 'value' if equity >= 0.60 else ('semi' if equity >= 0.40 else 'bluff')

                size_choice = choose_size_bucket(
                    intent=intent,
                    texture=texture,
                    spr=spr,
                    is_ip_postflop=is_ip_postflop,
                )

                # Evaluate a couple of sizes.
                pot_fracs = [size_choice.pot_fraction]
                if intent != 'value':
                    pot_fracs.append(max(0.25, size_choice.pot_fraction - 0.20))

                for frac in pot_fracs:
                    raise_sz = sizing_amount(
                        pot=state.pot,
                        bb=state.bb,
                        min_raise=state.min_raise,
                        stack=state.stacks[hero],
                        to_call=state.to_call,
                        pot_fraction=frac,
                    )
                    if raise_sz <= 0:
                        continue

                    fe = estimate_fold_equity(
                        opponent=opp_snap,
                        texture=texture,
                        street=state.street,
                        pot=state.pot,
                        bet_size=raise_sz,
                        is_raise=True,
                    )
                    ev = self._aggressive_ev(
                        equity=equity,
                        pot=state.pot,
                        to_call=state.to_call,
                        raise_size=raise_sz,
                        fe=fe,
                    )
                    if ActionType.RAISE in actions and raise_sz >= state.min_raise and ev > best_ev:
                        best_action = Action(ActionType.RAISE, raise_sz, hero)
                        best_ev = ev
                        ctx.fold_equity = fe
                        expl['size_label'] = size_choice.label
                        expl['size_frac'] = round(frac, 3)
                        expl['ev'] = round(ev, 3)
                        expl['reasoning'] = f'raise_{intent}_ev'

                # Consider all-in if available and SPR low.
                if ActionType.ALL_IN in actions and spr <= 3.0:
                    max_put = max(0.0, state.to_call + state.stacks[villain])
                    all_in_put = min(state.stacks[hero], max_put)
                    raise_sz = max(0.0, all_in_put - state.to_call)
                    fe = estimate_fold_equity(
                        opponent=opp_snap,
                        texture=texture,
                        street=state.street,
                        pot=state.pot,
                        bet_size=max(1.0, raise_sz),
                        is_raise=True,
                    )
                    ev = self._aggressive_ev(
                        equity=equity,
                        pot=state.pot,
                        to_call=state.to_call,
                        raise_size=raise_sz,
                        fe=fe,
                    )
                    if ev > best_ev:
                        best_action = Action(ActionType.ALL_IN, all_in_put, hero)
                        best_ev = ev
                        ctx.fold_equity = fe
                        expl['ev'] = round(ev, 3)
                        expl['reasoning'] = 'jam_ev_low_spr'

            expl['ev_best'] = round(best_ev, 3)
            if best_action is None:
                best_action = Action(ActionType.CALL if ActionType.CALL in actions else actions[0], state.to_call, hero)
                expl['reasoning'] = 'fallback_facing_bet'

            # Ensure explanation contains the final pick.
            expl['action'] = best_action.type.value
            return best_action, expl

        # ---- No bet to face (check or bet) ----
        best_action = None
        best_ev = 0.0

        # Check baseline
        if ActionType.CHECK in actions:
            best_action = Action(ActionType.CHECK, 0.0, hero)
            best_ev = 0.0

        # If betting is possible, decide value vs bluff.
        if ActionType.BET in actions or ActionType.ALL_IN in actions:
            # Base c-bet/bluff frequency.
            if state.street == 'FLOP':
                base_freq = 0.65 if is_ip_postflop else 0.55
                if texture.texture == 'wet':
                    base_freq -= 0.18
                elif texture.texture == 'dry':
                    base_freq += 0.08
                base_freq += (opp_snap.fold_to_cbet - 0.5) * 0.35
            else:
                base_freq = 0.45
                base_freq += (opp_snap.fold_to_cbet - 0.5) * 0.15

            base_freq = max(0.05, min(0.90, base_freq))

            intent = 'value' if equity >= 0.55 else ('semi' if equity >= 0.38 else 'bluff')

            # Stations: bluff less, value thinner.
            is_station = opp_snap.vpip >= 0.55 and opp_snap.fold_to_cbet <= 0.45
            if is_station and intent == 'bluff':
                base_freq *= 0.55
            if is_station and intent == 'value':
                intent = 'value'

            # Deterministic-ish frequency via RNG.
            do_bet = (equity >= 0.62) or (self.rng.random() < base_freq)

            if do_bet:
                size_choice = choose_size_bucket(
                    intent=intent,
                    texture=texture,
                    spr=spr,
                    is_ip_postflop=is_ip_postflop,
                )

                bet_sz = sizing_amount(
                    pot=state.pot,
                    bb=state.bb,
                    min_raise=state.min_raise,
                    stack=state.stacks[hero],
                    to_call=0.0,
                    pot_fraction=size_choice.pot_fraction,
                )

                if bet_sz > 0 and ActionType.BET in actions and bet_sz >= state.min_raise:
                    fe = estimate_fold_equity(
                        opponent=opp_snap,
                        texture=texture,
                        street=state.street,
                        pot=state.pot,
                        bet_size=bet_sz,
                        is_raise=False,
                    )
                    ctx.fold_equity = fe
                    ev = self._aggressive_ev(
                        equity=equity,
                        pot=state.pot,
                        to_call=0.0,
                        raise_size=bet_sz,
                        fe=fe,
                    )
                    if ev > best_ev:
                        best_action = Action(ActionType.BET, bet_sz, hero)
                        best_ev = ev
                        expl['size_label'] = size_choice.label
                        expl['size_frac'] = round(size_choice.pot_fraction, 3)
                        expl['reasoning'] = f'bet_{intent}_ev'
                        expl['ev'] = round(ev, 3)

                if ActionType.ALL_IN in actions and spr <= 1.8:
                    # Pure jam when SPR is tiny.
                    max_put = state.stacks[hero]
                    fe = estimate_fold_equity(
                        opponent=opp_snap,
                        texture=texture,
                        street=state.street,
                        pot=state.pot,
                        bet_size=max(1.0, max_put),
                        is_raise=False,
                    )
                    ev = self._aggressive_ev(
                        equity=equity,
                        pot=state.pot,
                        to_call=0.0,
                        raise_size=max_put,
                        fe=fe,
                    )
                    if ev > best_ev:
                        best_action = Action(ActionType.ALL_IN, max_put, hero)
                        best_ev = ev
                        ctx.fold_equity = fe
                        expl['reasoning'] = 'jam_low_spr'
                        expl['ev'] = round(ev, 3)

        expl.update(ctx.to_expl())
        expl['ev_best'] = round(best_ev, 3)
        expl['action'] = (best_action.type.value if best_action else 'check')

        if best_action is None:
            best_action = Action(ActionType.CHECK, 0.0, hero)
            expl['reasoning'] = 'fallback_no_bet'

        return best_action, expl
