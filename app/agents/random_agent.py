"""
app/agents/random_agent.py - Random agent (baseline benchmark)
Selects a random legal action. Bet/raise sizes are random within valid range.
"""
from __future__ import annotations
import random
from typing import Tuple, Dict

from app.agents.base import BaseAgent
from app.engine.state import GameState
from app.engine.actions import Action, ActionType, legal_actions


class RandomAgent(BaseAgent):
    def __init__(self, name: str = "Random"):
        super().__init__(name)

    def select_action(self, state: GameState) -> Tuple[Action, Dict]:
        actions = legal_actions(state)
        chosen_type = random.choice(actions)

        amount = 0.0
        if chosen_type in (ActionType.BET, ActionType.RAISE):
            # Random bet between min_raise and all-in
            player = state.to_act
            max_raise = state.stacks[player] - state.to_call
            min_r = state.min_raise
            if max_raise > min_r:
                amount = random.uniform(min_r, max_raise)
            else:
                amount = max_raise
            amount = max(amount, 0)

        action = Action(type=chosen_type, amount=amount, player=state.to_act)
        explanation = {'reasoning': 'random'}
        return action, explanation
