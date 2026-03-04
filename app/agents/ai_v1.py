"""
app/agents/ai_v1.py - AI v1: Rule-based + EV-based Texas Hold'em agent
Implements full preflop tier system and postflop equity decisions per PDF spec.
"""
from __future__ import annotations
import random
from typing import Tuple, Dict, List, Set

from app.agents.base import BaseAgent
from app.engine.state import GameState
from app.engine.actions import Action, ActionType, legal_actions
from app.engine.cards import Card
from app.eval.equity import monte_carlo_equity
from app.eval.ev import pot_odds, call_ev, bet_ev, raise_size_for_label
import config


# ------------------------------------------------------------------ #
# Preflop hand tier classification
# ------------------------------------------------------------------ #

# Hand tiers as frozensets of canonical hand strings
# Format: 'AAo' = offsuit, 'AKs' = suited, 'AA' = pair (always same suit implied)

TIER_S: Set[str] = {
    'AA', 'KK', 'QQ', 'JJ', 'AKs', 'AKo'
}

TIER_A: Set[str] = {
    'TT', '99',
    'AQs', 'AJs', 'ATs', 'AQo',
    'KQs', 'KQo',
}

TIER_B: Set[str] = {
    '88', '77', '66',
    'A9s', 'A8s', 'A7s', 'A6s', 'A5s',
    'KJs', 'KTs',
    'QJs', 'JTs', 'T9s',
}

TIER_C: Set[str] = {
    '55', '44', '33', '22',
    'QTs', 'J9s', 'T8s', '98s', '87s', '76s', '65s', '54s',
    'KJo', 'QJo',
}

SUITED_CONNECTORS = {'T9s', '98s', '87s', '76s', '65s', '54s', '43s'}


def _hand_key(cards: List[Card]) -> str:
    """
    Convert 2 hole cards to canonical hand key.
    Returns e.g. 'AKs', 'AKo', 'QQ', 'T9s'
    """
    c1, c2 = sorted(cards, key=lambda c: c.rank, reverse=True)
    r1 = _rank_char(c1.rank)
    r2 = _rank_char(c2.rank)
    if c1.rank == c2.rank:
        return f"{r1}{r2}"  # pair
    suited = 's' if c1.suit == c2.suit else 'o'
    return f"{r1}{r2}{suited}"


def _rank_char(rank: int) -> str:
    mapping = {14: 'A', 13: 'K', 12: 'Q', 11: 'J', 10: 'T'}
    return mapping.get(rank, str(rank))


def get_hand_tier(cards: List[Card]) -> str:
    """Returns 'S', 'A', 'B', 'C', or 'D'."""
    key = _hand_key(cards)
    if key in TIER_S:
        return 'S'
    if key in TIER_A:
        return 'A'
    if key in TIER_B:
        return 'B'
    if key in TIER_C:
        return 'C'
    return 'D'


# ------------------------------------------------------------------ #
# AI v1 Agent
# ------------------------------------------------------------------ #

class AIv1(BaseAgent):
    def __init__(self, name: str = "AI v1", seat: int = 0):
        super().__init__(name)
        self.seat = seat  # Which seat this agent occupies

    @staticmethod
    def _as_aggressive(
        action_type: ActionType, amount: float,
        stack: float, to_call: float,
        player: int, actions: List[ActionType]
    ) -> Action:
        """Return a RAISE/BET action, upgrading to ALL_IN when the total
        would consume the player's entire remaining stack."""
        total = amount + (to_call if action_type == ActionType.RAISE else 0.0)
        if total >= stack - 0.01 and ActionType.ALL_IN in actions:
            return Action(ActionType.ALL_IN, amount=stack, player=player)
        return Action(action_type, amount, player)

    def select_action(self, state: GameState) -> Tuple[Action, Dict]:
        player = state.to_act
        actions = legal_actions(state)
        my_hole = state.hole_cards[player]

        if state.street == 'PREFLOP':
            return self._preflop_decision(state, actions, my_hole, player)
        else:
            return self._postflop_decision(state, actions, my_hole, player)

    # ------------------------------------------------------------------ #
    # Preflop
    # ------------------------------------------------------------------ #

    def _preflop_decision(
        self, state: GameState, actions: List[ActionType],
        my_hole: List[Card], player: int
    ) -> Tuple[Action, Dict]:
        tier = get_hand_tier(my_hole)
        is_button = (player == state.button_seat)
        facing_raise = state.to_call > 0
        pot = state.pot
        bb = state.bb

        expl = {
            'tier': tier,
            'hand': _hand_key(my_hole),
            'street': 'PREFLOP',
            'facing_raise': facing_raise,
            'is_button': is_button,
        }

        # --- Facing a raise (3-bet / call / fold decision) ---
        if facing_raise:
            if tier == 'S':
                # 3-bet (re-raise)
                mult = config.THREBET_IP_MULT if is_button else config.THREBET_OOP_MULT
                raise_size = state.to_call * mult
                raise_size = min(raise_size, state.stacks[player] - state.to_call)
                raise_size = max(raise_size, state.min_raise)
                if ActionType.RAISE in actions and raise_size > 0 and state.stacks[player] > state.to_call:
                    expl['reasoning'] = f'Tier S: 3-bet x{mult}'
                    return self._as_aggressive(ActionType.RAISE, raise_size, state.stacks[player], state.to_call, player, actions), expl
                else:
                    expl['reasoning'] = 'Tier S: call (no raise option)'
                    return Action(ActionType.CALL, state.to_call, player), expl

            elif tier == 'A':
                # Mostly call, 25% 3-bet
                if ActionType.RAISE in actions and random.random() < 0.25 and state.stacks[player] > state.to_call:
                    mult = config.THREBET_IP_MULT if is_button else config.THREBET_OOP_MULT
                    raise_size = state.to_call * mult
                    raise_size = min(raise_size, state.stacks[player] - state.to_call)
                    raise_size = max(raise_size, state.min_raise)
                    expl['reasoning'] = 'Tier A: 3-bet (25% freq)'
                    return self._as_aggressive(ActionType.RAISE, raise_size, state.stacks[player], state.to_call, player, actions), expl
                expl['reasoning'] = 'Tier A: call'
                return Action(ActionType.CALL, state.to_call, player), expl

            elif tier == 'B':
                # Mostly call, some folds
                if random.random() < 0.2 and ActionType.FOLD in actions:
                    expl['reasoning'] = 'Tier B: fold vs aggression'
                    return Action(ActionType.FOLD, 0, player), expl
                if ActionType.CALL in actions:
                    expl['reasoning'] = 'Tier B: call'
                    return Action(ActionType.CALL, state.to_call, player), expl

            else:  # C or D
                if ActionType.FOLD in actions:
                    expl['reasoning'] = f'Tier {tier}: fold vs raise'
                    return Action(ActionType.FOLD, 0, player), expl
                expl['reasoning'] = 'call (no fold option)'
                return Action(ActionType.CALL, state.to_call, player), expl

        # --- Opening (no raise yet) ---
        open_size = config.OPEN_SIZE_BB * bb

        if tier in ('S', 'A'):
            if ActionType.RAISE in actions and state.stacks[player] > open_size:
                expl['reasoning'] = f'Tier {tier}: open raise {config.OPEN_SIZE_BB}bb'
                return self._as_aggressive(ActionType.RAISE, open_size, state.stacks[player], state.to_call, player, actions), expl
            elif ActionType.BET in actions and state.stacks[player] > open_size:
                expl['reasoning'] = f'Tier {tier}: open bet {config.OPEN_SIZE_BB}bb'
                return self._as_aggressive(ActionType.BET, open_size, state.stacks[player], state.to_call, player, actions), expl
            elif ActionType.CALL in actions:
                expl['reasoning'] = f'Tier {tier}: call (no raise option)'
                return Action(ActionType.CALL, state.to_call, player), expl
            else:
                expl['reasoning'] = f'Tier {tier}: check'
                return Action(ActionType.CHECK, 0, player), expl

        elif tier == 'B':
            # 60% raise, 40% call/check
            if random.random() < config.TIER_B_RAISE_PROB:
                if ActionType.RAISE in actions and state.stacks[player] > open_size:
                    expl['reasoning'] = 'Tier B: open raise (60% freq)'
                    return self._as_aggressive(ActionType.RAISE, open_size, state.stacks[player], state.to_call, player, actions), expl
                if ActionType.BET in actions and state.stacks[player] > open_size:
                    expl['reasoning'] = 'Tier B: open bet (60% freq)'
                    return self._as_aggressive(ActionType.BET, open_size, state.stacks[player], state.to_call, player, actions), expl
            # Fall through to check/call
            if ActionType.CHECK in actions:
                expl['reasoning'] = 'Tier B: check (40% no-raise)'
                return Action(ActionType.CHECK, 0, player), expl
            if ActionType.CALL in actions:
                expl['reasoning'] = 'Tier B: call (40% no-raise)'
                return Action(ActionType.CALL, state.to_call, player), expl

        elif tier == 'C':
            # Usually check/call
            if ActionType.CHECK in actions:
                expl['reasoning'] = 'Tier C: check'
                return Action(ActionType.CHECK, 0, player), expl
            if ActionType.CALL in actions:
                expl['reasoning'] = 'Tier C: call'
                return Action(ActionType.CALL, state.to_call, player), expl

        else:  # Tier D
            if ActionType.CHECK in actions:
                expl['reasoning'] = 'Tier D: check'
                return Action(ActionType.CHECK, 0, player), expl
            if ActionType.FOLD in actions:
                expl['reasoning'] = 'Tier D: fold'
                return Action(ActionType.FOLD, 0, player), expl

        # Fallback
        return self._fallback(actions, player, state, expl)

    # ------------------------------------------------------------------ #
    # Postflop (equity-based)
    # ------------------------------------------------------------------ #

    def _postflop_decision(
        self, state: GameState, actions: List[ActionType],
        my_hole: List[Card], player: int
    ) -> Tuple[Action, Dict]:
        pot = state.pot
        to_call = state.to_call
        bb = state.bb

        # Calculate equity via Monte Carlo
        equity = monte_carlo_equity(
            hole_cards=my_hole,
            board=state.board,
            time_budget_ms=config.MC_TIME_BUDGET_MS,
            min_samples=config.MC_MIN_SAMPLES,
            max_samples=config.MC_MAX_SAMPLES,
        )

        odds = pot_odds(to_call, pot) if to_call > 0 else 0.0
        margin = config.MARGIN

        expl = {
            'street': state.street,
            'equity': round(equity, 4),
            'pot_odds': round(odds, 4),
            'pot': pot,
            'to_call': to_call,
        }

        # --- Facing a bet ---
        if to_call > 0:
            # Fold if equity is well below pot odds
            if equity < odds - margin:
                if ActionType.FOLD in actions:
                    expl['reasoning'] = f'fold: equity({equity:.2%}) < pot_odds({odds:.2%}) - margin'
                    return Action(ActionType.FOLD, 0, player), expl
            # Consider raising if strong equity
            if equity >= 0.60 and ActionType.RAISE in actions:
                raise_size = raise_size_for_label('large', pot, bb)
                raise_size = min(raise_size, state.stacks[player] - to_call)
                if raise_size >= state.min_raise:
                    expl['reasoning'] = f'raise: equity={equity:.2%} (large)'
                    expl['size_label'] = 'large'
                    return self._as_aggressive(ActionType.RAISE, raise_size, state.stacks[player], to_call, player, actions), expl
            # Call if break-even or better
            if equity >= odds - margin:
                if ActionType.CALL in actions:
                    expl['reasoning'] = f'call: equity({equity:.2%}) >= pot_odds({odds:.2%}) - margin'
                    return Action(ActionType.CALL, to_call, player), expl
            # Default fold
            if ActionType.FOLD in actions:
                expl['reasoning'] = 'fold: default postflop'
                return Action(ActionType.FOLD, 0, player), expl

        # --- No bet to face (check or bet) ---
        elif to_call == 0:
            if equity >= 0.60:
                # Value bet large
                size_label = 'large'
                bet = raise_size_for_label(size_label, pot, bb)
                bet = min(bet, state.stacks[player])
                if ActionType.BET in actions and bet >= state.min_raise:
                    expl['reasoning'] = f'value_bet: equity={equity:.2%}'
                    expl['size_label'] = size_label
                    return self._as_aggressive(ActionType.BET, bet, state.stacks[player], 0.0, player, actions), expl

            elif equity >= 0.50:
                # Thin value bet medium
                size_label = 'medium'
                bet = raise_size_for_label(size_label, pot, bb)
                bet = min(bet, state.stacks[player])
                if ActionType.BET in actions and bet >= state.min_raise:
                    expl['reasoning'] = f'thin_value_bet: equity={equity:.2%}'
                    expl['size_label'] = size_label
                    return self._as_aggressive(ActionType.BET, bet, state.stacks[player], 0.0, player, actions), expl

            elif 0.30 <= equity < 0.45:
                # Semi-bluff with some frequency
                if random.random() < equity:  # probability proportional to equity
                    size_label = 'small'
                    bet = raise_size_for_label(size_label, pot, bb)
                    bet = min(bet, state.stacks[player])
                    if ActionType.BET in actions and bet >= state.min_raise:
                        expl['reasoning'] = f'semi_bluff: equity={equity:.2%}'
                        expl['size_label'] = size_label
                        return self._as_aggressive(ActionType.BET, bet, state.stacks[player], 0.0, player, actions), expl

            # Check everything else
            if ActionType.CHECK in actions:
                expl['reasoning'] = f'check: equity={equity:.2%}'
                return Action(ActionType.CHECK, 0, player), expl

        return self._fallback(actions, player, state, expl)

    # ------------------------------------------------------------------ #
    # Fallback
    # ------------------------------------------------------------------ #

    def _fallback(
        self, actions: List[ActionType], player: int,
        state: GameState, expl: Dict
    ) -> Tuple[Action, Dict]:
        """Default fallback action."""
        expl['reasoning'] = 'fallback'
        if ActionType.CHECK in actions:
            return Action(ActionType.CHECK, 0, player), expl
        if ActionType.CALL in actions:
            return Action(ActionType.CALL, state.to_call, player), expl
        if ActionType.FOLD in actions:
            return Action(ActionType.FOLD, 0, player), expl
        # Should never reach here
        return Action(actions[0], 0, player), expl
