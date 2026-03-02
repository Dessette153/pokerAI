"""
app/agents/simple_agent.py - Simple rule-based agent (benchmark vs AI v1)
Strategy: call/check always, raise 30% of the time with 2x pot bet
"""
from __future__ import annotations
import random
from typing import Tuple, Dict

from app.agents.base import BaseAgent
from app.engine.state import GameState
from app.engine.actions import Action, ActionType, legal_actions


class SimpleAgent(BaseAgent):
    """
    Simple strategy agent:
    - Always calls when facing a bet
    - 30% of the time bets/raises (random bet size)
    - Otherwise checks
    """
    def __init__(self, name: str = "Simple", raise_freq: float = 0.30):
        super().__init__(name)
        self.raise_freq = raise_freq

    def select_action(self, state: GameState) -> Tuple[Action, Dict]:
        actions = legal_actions(state)
        player = state.to_act

        # Fold is only legal when facing a bet; simple agent never folds
        if ActionType.FOLD in actions:
            actions = [a for a in actions if a != ActionType.FOLD]
        if not actions:
            actions = legal_actions(state)

        # Facing a bet: always call
        if state.to_call > 0:
            if ActionType.RAISE in actions and random.random() < self.raise_freq:
                # Occasionally raise
                min_r = state.min_raise
                amount = min_r * 2
                amount = min(amount, state.stacks[player] - state.to_call)
                amount = max(amount, min_r)
                action = Action(type=ActionType.RAISE, amount=amount, player=player)
                return action, {'reasoning': 'simple_raise'}
            action = Action(type=ActionType.CALL, amount=state.to_call, player=player)
            return action, {'reasoning': 'simple_call'}

        # No bet: check or occasionally bet
        if ActionType.BET in actions and random.random() < self.raise_freq:
            bet = max(state.bb, state.pot * 0.5)
            bet = min(bet, state.stacks[player])
            action = Action(type=ActionType.BET, amount=bet, player=player)
            return action, {'reasoning': 'simple_bet'}

        action = Action(type=ActionType.CHECK, amount=0.0, player=player)
        return action, {'reasoning': 'simple_check'}
