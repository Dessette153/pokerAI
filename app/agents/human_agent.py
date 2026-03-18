"""app/agents/human_agent.py - Human-controlled agent for CLI play.

This agent prompts the user for input on its turn, validates the action strictly
against engine legal actions, and returns an Action compatible with the current
engine + simulator.

Design goals:
- Keep engine unchanged
- Keep AI vs AI simulation unchanged
- Do not leak opponent hole cards before showdown
- Make parsing/validation testable by injecting I/O functions
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Tuple

from app.agents.base import BaseAgent
from app.engine.actions import Action, ActionType, legal_actions
from app.engine.state import GameState


OutputFn = Callable[[str], None]
InputFn = Callable[[str], str]


def _cards_str(cards: Iterable) -> str:
    return " ".join(str(c) for c in cards) if cards else "-"


def render_hero_view(state: GameState, hero_seat: int, max_actions: int = 12) -> str:
    """Render a human-friendly view of the state without leaking hidden info."""
    villain_seat = 1 - hero_seat

    lines: List[str] = []
    lines.append("\n" + "=" * 68)
    lines.append(f"Hand {state.hand_id} | Street: {state.street} | To act: P{state.to_act}")
    lines.append("-" * 68)

    lines.append(f"Board : {_cards_str(state.board)}")
    lines.append(f"Pot   : {state.pot:.0f}")
    lines.append(
        f"Stacks: P0={state.stacks[0]:.0f}  P1={state.stacks[1]:.0f}"
        + ("  (P0 ALL-IN)" if state.all_in[0] else "")
        + ("  (P1 ALL-IN)" if state.all_in[1] else "")
    )

    hero_hole = state.hole_cards[hero_seat]
    lines.append(f"Your cards (P{hero_seat}): {_cards_str(hero_hole)}")

    # Only reveal opponent hole cards after terminal showdown.
    if state.is_terminal:
        showdown = None
        for a in reversed(state.action_history):
            if a.get("type") == "showdown":
                showdown = a
                break
        if showdown and showdown.get("hole_cards"):
            opp_cards = showdown["hole_cards"][villain_seat]
            lines.append(f"Opponent cards (P{villain_seat}): {' '.join(opp_cards)}")

    lines.append("-" * 68)

    if not state.is_terminal:
        la = legal_actions(state)
        la_str = ", ".join(a.value for a in la)
        lines.append(
            f"To call: {state.to_call:.0f} | Min raise: {state.min_raise:.0f} | Legal: {la_str}"
        )

    # Action history (avoid printing showdown hole_cards mid-hand)
    if state.action_history:
        lines.append("Recent actions:")
        shown = 0
        for a in reversed(state.action_history):
            if a.get("type") == "showdown":
                # Do not show hole cards in the log, even at showdown.
                winner = a.get("winner")
                lines.append(f"  showdown: winner={winner} pot_won={a.get('pot_won')}")
                shown += 1
            elif a.get("type") == "deal_board":
                lines.append(f"  deal {a.get('street')}: {' '.join(a.get('cards') or [])}")
                shown += 1
            else:
                p = a.get("player")
                t = a.get("type")
                amt = a.get("amount", 0.0)
                if t in (ActionType.BET.value, ActionType.RAISE.value, ActionType.CALL.value, ActionType.ALL_IN.value):
                    lines.append(f"  P{p} {t} {amt:.0f}")
                else:
                    lines.append(f"  P{p} {t}")
                shown += 1

            if shown >= max_actions:
                break

    return "\n".join(lines)


@dataclass(frozen=True)
class ParseResult:
    action: Action


def parse_human_action(text: str, state: GameState) -> Action:
    """Parse user input into an Action. Raises ValueError on invalid."""
    raw = (text or "").strip().lower()
    if not raw:
        raise ValueError("Empty input")

    # Normalize
    raw = raw.replace("-", "_")
    parts = raw.split()
    cmd = parts[0]

    aliases = {
        "f": "fold",
        "x": "check",
        "k": "check",
        "c": "call",
        "a": "all_in",
        "allin": "all_in",
        "ai": "all_in",
    }
    cmd = aliases.get(cmd, cmd)

    if cmd in ("fold", "check", "call", "all_in"):
        return Action(type=ActionType(cmd))

    if cmd in ("bet", "raise"):
        if len(parts) != 2:
            raise ValueError(f"Usage: {cmd} <amount>")
        try:
            amt = float(parts[1])
        except ValueError as e:
            raise ValueError("Amount must be a number") from e
        if amt != amt or amt <= 0:
            raise ValueError("Amount must be > 0")
        return Action(type=ActionType(cmd), amount=amt)

    if cmd in ("help", "h", "?"):
        raise ValueError(
            "Commands: fold(f), check(x), call(c), bet <amt>, raise <amt>, all_in(a)"
        )

    raise ValueError(f"Unknown command: {cmd}")


def validate_human_action(action: Action, state: GameState) -> None:
    """Strictly validate the action against current state.

    Notes:
    - Engine will cap certain actions (e.g. ALL_IN), but for human input we
      reject out-of-range sizes instead of silently converting.
    """
    la = legal_actions(state)
    if action.type not in la:
        raise ValueError(f"Illegal action now. Legal: {', '.join(a.value for a in la)}")

    player = state.to_act
    stack = state.stacks[player]
    to_call = state.to_call

    if action.type in (ActionType.FOLD, ActionType.CHECK, ActionType.CALL, ActionType.ALL_IN):
        return

    if action.type == ActionType.BET:
        if to_call > 0:
            raise ValueError("Cannot bet when facing a bet; use call/raise")
        if action.amount < state.min_raise:
            raise ValueError(f"Bet must be at least {state.min_raise:.0f}")
        if action.amount > stack:
            raise ValueError("Bet exceeds your stack; use all_in")
        return

    if action.type == ActionType.RAISE:
        if to_call <= 0:
            raise ValueError("Cannot raise when there is nothing to call; use bet")
        if stack <= to_call:
            raise ValueError("You do not have chips to raise; call or fold")
        if action.amount < state.min_raise:
            raise ValueError(f"Raise size must be at least {state.min_raise:.0f}")
        max_raise_size = stack - to_call
        if action.amount > max_raise_size:
            raise ValueError("Raise exceeds available chips after calling; use all_in")
        return

    raise ValueError("Unsupported action type")


class HumanAgent(BaseAgent):
    """Human-controlled agent.

    Use in CLI mode. Inject `input_fn` and `output_fn` for testability.

    Convention:
    - `bet <amt>` uses absolute bet size (since to_call == 0)
    - `raise <amt>` uses raise size *above* the call amount (not total-to)
    """

    def __init__(
        self,
        name: str = "Hero",
        seat: int | None = None,
        input_fn: InputFn | None = None,
        output_fn: OutputFn | None = None,
    ):
        super().__init__(name)
        self.seat = seat
        self._input = input_fn or (lambda prompt: input(prompt))
        self._out = output_fn or (lambda msg: print(msg))

    def select_action(self, state: GameState) -> Tuple[Action, Dict]:
        if self.seat is not None and state.to_act != self.seat:
            # This is a wiring error; be explicit to avoid acting for wrong player.
            raise RuntimeError(
                f"HumanAgent wired to seat {self.seat} but state.to_act is {state.to_act}"
            )

        hero_seat = state.to_act

        while True:
            self._out(render_hero_view(state, hero_seat=hero_seat))

            prompt = "\nYour action (help for commands): "
            raw = self._input(prompt)
            try:
                action = parse_human_action(raw, state)
                validate_human_action(action, state)
                return action, {"reasoning": "human"}
            except ValueError as e:
                # Print message and reprompt safely.
                self._out(f"Invalid input: {e}")
