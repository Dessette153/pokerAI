"""
app/agents/allin_agent.py - All-in agent
Strategy: always goes all-in (shove). Calls any bet, shoves when able to bet/raise.
"""
from __future__ import annotations
from typing import Tuple, Dict

from app.agents.base import BaseAgent
from app.engine.state import GameState
from app.engine.actions import Action, ActionType, legal_actions


class AllInAgent(BaseAgent):
    """
    All-in strategy agent:
    - Facing a bet: goes all-in (raise to stack if possible, else call)
    - No bet: shoves all-in (bet stack)
    """
    def __init__(self, name: str = "All-In"):
        super().__init__(name)

    def select_action(self, state: GameState) -> Tuple[Action, Dict]:
        actions = legal_actions(state)
        player = state.to_act
        stack = state.stacks[player]

        if state.to_call > 0:
            # Facing a bet: raise all-in if possible
            if ActionType.RAISE in actions:
                shove = stack - state.to_call
                shove = max(shove, state.min_raise)
                action = Action(type=ActionType.RAISE, amount=shove, player=player)
                return action, {'reasoning': 'allin_shove'}
            # Can't raise (not enough chips): call
            action = Action(type=ActionType.CALL, amount=state.to_call, player=player)
            return action, {'reasoning': 'allin_call'}

        # No bet: bet entire stack
        if ActionType.BET in actions:
            action = Action(type=ActionType.BET, amount=stack, player=player)
            return action, {'reasoning': 'allin_bet'}

        action = Action(type=ActionType.CHECK, amount=0.0, player=player)
        return action, {'reasoning': 'allin_check'}
