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

        # Always go all-in if possible
        stack = state.stacks[player]
        if ActionType.ALL_IN in actions:
            action = Action(type=ActionType.ALL_IN, amount=stack, player=player)
            return action, {'reasoning': 'allin_shove'}

        # Fallback: call or check (e.g. already all-in, just need to check/call)
        if ActionType.CALL in actions:
            action = Action(type=ActionType.CALL, player=player)
            return action, {'reasoning': 'allin_call'}

        action = Action(type=ActionType.CHECK, amount=0.0, player=player)
        return action, {'reasoning': 'allin_check'}
