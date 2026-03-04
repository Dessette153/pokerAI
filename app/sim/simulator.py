"""
app/sim/simulator.py - Generator-based hand and session simulator

The simulator yields SimEvent objects after each action, allowing the UI
to consume events one at a time and control timing.

SimEvent types:
- "hand_start":  new hand began
- "action":      player took an action
- "street":      new street started (board cards dealt)
- "hand_end":    hand completed (with wasFolder flag and snapshots)
"""
from __future__ import annotations
import copy
from dataclasses import dataclass, field
from typing import Generator, List, Optional, Dict, Any

from app.engine.engine import GameEngine
from app.engine.state import GameState, HandResult, StreetSnapshot
from app.engine.actions import Action, ActionType, legal_actions
from app.agents.base import BaseAgent


@dataclass
class SimEvent:
    type: str                           # "hand_start" | "action" | "street" | "hand_end"
    state: GameState                    # current game state
    action: Optional[dict] = None      # last action taken (for "action" events)
    street: Optional[str] = None       # new street name (for "street" events)
    result: Optional[HandResult] = None  # set for "hand_end"
    snapshots: List[StreetSnapshot] = field(default_factory=list)
    was_fold: bool = False


def simulate_hand(
    engine: GameEngine,
    agents: List[BaseAgent],
    hand_id: int,
    stacks: List[float],
    button: int,
) -> Generator[SimEvent, None, HandResult]:
    """
    Generator that simulates one complete hand.
    Yields SimEvent after each action / street change.
    Returns HandResult when complete.
    """
    state, deck = engine.new_hand(hand_id, stacks, button)
    initial_stacks = list(stacks)

    # Track street snapshots for revert capability
    snapshots: List[StreetSnapshot] = []
    # Current street snapshot being built
    current_snap = StreetSnapshot(
        street=state.street,
        board_at_start=list(state.board),
        stacks_at_start=list(state.stacks),
        pot_at_start=state.pot,
        actions=[],
        state_at_start=state.copy(),
    )

    yield SimEvent(type='hand_start', state=state.copy())

    prev_street = state.street

    while not state.is_terminal:
        player = state.to_act
        agent = agents[player]

        # Get action from agent
        action, explanation = agent.select_action(state)
        action.explanation = explanation
        action.player = player

        # Record action in current snapshot
        action_record = {
            'player': player,
            'type': action.type.value,
            'amount': action.amount,
            'explanation': explanation,
        }

        prev_street = state.street

        # Apply action to engine
        state = engine.apply_action(state, action, deck)

        # Sync processed amount back to action_record (engine may cap/adjust it,
        # e.g. for ALL_IN the actual amount is the player's stack, not Action.amount)
        if state.action_history:
            last = state.action_history[-1]
            processed_amount = last.get('amount', action_record['amount'])
            if processed_amount != 0 or action.type.value == 'all_in':
                action_record['amount'] = processed_amount
            if last.get('uncalled_returned'):
                action_record['uncalled_returned'] = last['uncalled_returned']
            if last.get('all_in'):
                action_record['all_in'] = True

        action_record['pot_after'] = state.pot
        action_record['stacks_after'] = list(state.stacks)
        current_snap.actions.append(action_record)

        yield SimEvent(
            type='action',
            state=state.copy(),
            action=action_record,
        )

        # Check if street changed
        if state.street != prev_street and not state.is_terminal:
            # Finalize current snapshot
            current_snap.state_at_end = state.copy()
            snapshots.append(current_snap)

            # Start new snapshot
            current_snap = StreetSnapshot(
                street=state.street,
                board_at_start=list(state.board),
                stacks_at_start=list(state.stacks),
                pot_at_start=state.pot,
                actions=[],
                state_at_start=state.copy(),
            )

            yield SimEvent(
                type='street',
                state=state.copy(),
                street=state.street,
                snapshots=list(snapshots),
            )

    # Finalize last snapshot
    current_snap.state_at_end = state.copy()
    snapshots.append(current_snap)

    # Build HandResult
    was_fold = False
    fold_by = None
    for action_dict in state.action_history:
        if action_dict.get('type') == 'fold':
            was_fold = True
            fold_by = action_dict.get('player')
            break

    net_chips = [state.stacks[i] - initial_stacks[i] for i in range(2)]

    # Get showdown scores if available
    showdown_scores = None
    for action_dict in reversed(state.action_history):
        if action_dict.get('type') == 'showdown':
            showdown_scores = action_dict.get('scores')
            break

    result = HandResult(
        hand_id=hand_id,
        winner=state.winner if state.winner is not None else -1,
        pot_won=state.pot_won or 0.0,
        was_fold=was_fold,
        fold_by=fold_by,
        net_chips=net_chips,
        snapshots=snapshots,
        final_state=state,
        showdown_scores=showdown_scores,
    )

    yield SimEvent(
        type='hand_end',
        state=state.copy(),
        result=result,
        snapshots=snapshots,
        was_fold=was_fold,
    )

    return result


class SessionSimulator:
    """
    Manages a multi-hand session between two agents.
    Provides stack management and button rotation.
    """

    def __init__(
        self,
        engine: GameEngine,
        agents: List[BaseAgent],
        starting_stacks: Optional[List[float]] = None,
        rebuy_to: Optional[float] = None,
        rebuy_both: bool = True,
    ):
        self.engine = engine
        self.agents = agents
        self.stacks = starting_stacks or [10_000.0, 10_000.0]
        self.rebuy_to = rebuy_to  # rebuy short stacks to this amount (or None)
        self.rebuy_both = rebuy_both  # if True, reset BOTH players on rebuy (conserves chips)
        self.button = 0
        self.hand_id = 1
        self.results: List[HandResult] = []

    def next_hand_generator(self) -> Generator[SimEvent, None, HandResult]:
        """Get generator for the next hand."""
        stacks = list(self.stacks)

        # Rebuy if needed
        if self.rebuy_to:
            if self.rebuy_both:
                # If any player is short, reset BOTH to starting stack.
                # This preserves chip conservation - no free chips are created.
                if any(s < self.engine.bb * 10 for s in stacks):
                    stacks = [self.rebuy_to, self.rebuy_to]
            else:
                for i in range(2):
                    if stacks[i] < self.engine.bb * 10:
                        stacks[i] = self.rebuy_to

        gen = simulate_hand(
            self.engine, self.agents, self.hand_id, stacks, self.button
        )
        return gen

    def record_result(self, result: HandResult) -> None:
        """Update internal state after a hand completes."""
        self.stacks = list(result.final_state.stacks)
        self.button = 1 - self.button  # alternate button
        self.hand_id += 1
        self.results.append(result)

    @property
    def current_hand_id(self) -> int:
        return self.hand_id
