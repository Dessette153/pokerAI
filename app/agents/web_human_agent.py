"""app/agents/web_human_agent.py - Human agent controlled via web UI.

This agent blocks (in a background simulation thread) until an action is
submitted by the connected browser client.

The server code is responsible for:
- emitting a UI prompt when `prompt_fn` is called
- validating incoming actions and calling `set_action`

This keeps the agent independent from Flask/SocketIO.
"""

from __future__ import annotations

import threading
from typing import Callable, Dict, Optional, Tuple

from app.agents.base import BaseAgent
from app.engine.actions import Action
from app.engine.state import GameState


PromptFn = Callable[[GameState], None]


class WebHumanAgent(BaseAgent):
    def __init__(self, name: str = 'Hero', seat: int = 0, prompt_fn: PromptFn | None = None):
        super().__init__(name)
        self.seat = seat
        self._prompt_fn = prompt_fn or (lambda _s: None)

        self._lock = threading.Lock()
        self._waiting = False
        self._pending_state: Optional[GameState] = None
        self._pending_action: Optional[Action] = None
        self._evt = threading.Event()

    @property
    def pending_state(self) -> Optional[GameState]:
        with self._lock:
            return self._pending_state.copy() if self._pending_state else None

    @property
    def waiting_for_action(self) -> bool:
        with self._lock:
            return self._waiting

    def set_action(self, action: Action) -> None:
        with self._lock:
            if not self._waiting:
                return
            self._pending_action = action
            self._evt.set()

    def select_action(self, state: GameState) -> Tuple[Action, Dict]:
        if state.to_act != self.seat:
            raise RuntimeError(
                f"WebHumanAgent wired to seat {self.seat} but state.to_act is {state.to_act}"
            )

        with self._lock:
            self._waiting = True
            self._pending_state = state.copy()
            self._pending_action = None
            self._evt.clear()

        # Prompt the UI (non-blocking)
        self._prompt_fn(self._pending_state)

        # Wait for UI submission
        self._evt.wait()

        with self._lock:
            self._waiting = False
            action = self._pending_action
            self._pending_state = None
            self._pending_action = None

        if action is None:
            raise RuntimeError('WebHumanAgent unblocked without an action')

        return action, {'reasoning': 'human'}
