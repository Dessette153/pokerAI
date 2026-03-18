"""
app/engine/engine.py - GameEngine: new hand, betting rounds, streets, showdown

Betting round logic:
- Each player has a `voluntary_acted` flag (reset each street)
- Round ends when BOTH players have voluntarily acted AND to_call == 0
- This naturally handles BB option in preflop
"""
from __future__ import annotations
import copy
from typing import List, Optional, Tuple

from app.engine.cards import Card, Deck
from app.engine.state import GameState, HandResult, StreetSnapshot
from app.engine.actions import Action, ActionType, legal_actions
from app.engine.evaluator import evaluate_hand, compare_hands

STREETS = ['PREFLOP', 'FLOP', 'TURN', 'RIVER']


class GameEngine:
    def __init__(self, sb: float, bb: float):
        self.sb = sb
        self.bb = bb

    # ------------------------------------------------------------------ #
    # Hand initialization
    # ------------------------------------------------------------------ #

    def new_hand(self, hand_id: int, stacks: List[float], button: int) -> Tuple[GameState, Deck]:
        """Set up a new hand. Returns (initial GameState, shuffled Deck)."""
        deck = Deck()
        deck.shuffle()
        bb_seat = 1 - button

        # Deal hole cards
        hole_cards = [deck.deal(2), deck.deal(2)]

        # Post blinds (handle short stacks)
        sb_post = min(self.sb, stacks[button])
        bb_post = min(self.bb, stacks[bb_seat])
        new_stacks = list(stacks)
        new_stacks[button] -= sb_post
        new_stacks[bb_seat] -= bb_post
        pot = sb_post + bb_post

        street_invested = [0.0, 0.0]
        street_invested[button] = sb_post
        street_invested[bb_seat] = bb_post

        # SB needs to complete to BB level
        to_call = bb_post - sb_post

        all_in = [new_stacks[0] == 0, new_stacks[1] == 0]

        state = GameState(
            hand_id=hand_id,
            street='PREFLOP',
            button_seat=button,
            to_act=button,          # SB acts first preflop
            pot=pot,
            stacks=new_stacks,
            bb=self.bb,
            sb=self.sb,
            board=[],
            hole_cards=hole_cards,
            to_call=to_call,
            last_raise=self.bb,
            min_raise=self.bb,
            action_history=[],
            street_actions=[],
            voluntary_acted=[False, False],  # neither has voluntarily acted
            is_terminal=False,
            all_in=all_in,
            street_invested=street_invested,
            total_invested=[
                sb_post if button == 0 else bb_post,
                bb_post if button == 0 else sb_post,
            ],
        )
        return state, deck

    # ------------------------------------------------------------------ #
    # Action application
    # ------------------------------------------------------------------ #

    def apply_action(self, state: GameState, action: Action, deck: Deck) -> GameState:
        """Return a new GameState after applying the action. Deck used for board dealing."""
        s = state.copy()
        player = s.to_act
        opponent = 1 - player

        # Track call owed before this action (useful for sizing raises / all-ins)
        call_owed_before = s.to_call

        action_dict = {
            'player': player,
            'type': action.type.value,
            'amount': 0.0,
            'pot_before': s.pot,
            'stacks_before': list(s.stacks),
            'explanation': action.explanation or {},
        }

        if action.type == ActionType.FOLD:
            s.is_terminal = True
            s.winner = opponent
            s.pot_won = s.pot
            s.stacks[opponent] += s.pot
            action_dict['result'] = 'fold'

        elif action.type == ActionType.CHECK:
            s.voluntary_acted[player] = True

        elif action.type == ActionType.CALL:
            call_amount = min(s.to_call, s.stacks[player])
            s.stacks[player] -= call_amount
            s.pot += call_amount
            s.street_invested[player] += call_amount
            s.total_invested[player] += call_amount
            if s.stacks[player] == 0:
                s.all_in[player] = True
                # Heads-up all-in for less: return uncalled excess to opponent.
                # Opponent over-bet more than this player could match, so their
                # extra chips are not eligible for the pot and must be refunded.
                uncalled = s.to_call - call_amount
                if uncalled > 0:
                    s.stacks[opponent] += uncalled
                    s.pot -= uncalled
                    s.street_invested[opponent] -= uncalled
                    s.total_invested[opponent] -= uncalled
                    # If we refunded chips, the opponent is not actually all-in anymore.
                    if s.stacks[opponent] > 0:
                        s.all_in[opponent] = False
                    action_dict['uncalled_returned'] = uncalled
            s.voluntary_acted[player] = True
            action_dict['amount'] = call_amount

        elif action.type in (ActionType.BET, ActionType.RAISE):
            # action.amount = size of bet/raise on top of any call owed
            raise_size = max(action.amount, s.min_raise)
            call_owed = s.to_call
            total_put = min(call_owed + raise_size, s.stacks[player])
            actual_raise = total_put - call_owed

            s.stacks[player] -= total_put
            s.pot += total_put
            s.street_invested[player] += total_put
            s.total_invested[player] += total_put

            if s.stacks[player] == 0:
                s.all_in[player] = True

            # Update call owed by opponent
            s.to_call = s.street_invested[player] - s.street_invested[opponent]
            s.last_raise = actual_raise
            s.min_raise = actual_raise

            # After a bet/raise, opponent must act again
            s.voluntary_acted[player] = True
            s.voluntary_acted[opponent] = False

            action_dict['amount'] = total_put
            action_dict['raise_size'] = actual_raise

        elif action.type == ActionType.ALL_IN:
            # Player commits an all-in amount.
            # Heads-up simplification: you cannot commit more chips than the
            # opponent can cover. Cap the committed amount to:
            #   max_put = to_call + opponent_remaining_stack
            # This prevents "all-in" actions larger than the opponent's stack.
            max_put = max(0.0, s.to_call + s.stacks[opponent])
            all_in_amount = min(s.stacks[player], max_put)

            s.stacks[player] -= all_in_amount
            s.pot += all_in_amount
            s.street_invested[player] += all_in_amount
            s.total_invested[player] += all_in_amount
            s.all_in[player] = (s.stacks[player] == 0)

            # net_to_call: how much opponent must still put in after this
            net_to_call = s.street_invested[player] - s.street_invested[opponent]
            if net_to_call > 0:
                # Raise-all-in: opponent must respond
                s.to_call = net_to_call
                actual_raise = max(0.0, all_in_amount - call_owed_before)
                s.last_raise = actual_raise
                # Keep min_raise unchanged unless this is a bigger raise size.
                if actual_raise > 0:
                    s.min_raise = max(s.min_raise, actual_raise)
                s.voluntary_acted[player] = True
                s.voluntary_acted[opponent] = False
            else:
                # Call-all-in for less: return the uncalled portion to opponent
                uncalled = -net_to_call  # = opponent_invested - player_invested
                if uncalled > 0:
                    s.stacks[opponent] += uncalled
                    s.pot -= uncalled
                    s.street_invested[opponent] -= uncalled
                    s.total_invested[opponent] -= uncalled
                    if s.stacks[opponent] > 0:
                        s.all_in[opponent] = False
                    action_dict['uncalled_returned'] = uncalled
                s.to_call = 0
                s.voluntary_acted[player] = True

            action_dict['amount'] = all_in_amount
            if s.all_in[player]:
                action_dict['all_in'] = True

        action_dict['pot_after'] = s.pot
        action_dict['stacks_after'] = list(s.stacks)
        s.action_history.append(action_dict)
        s.street_actions.append(action_dict)

        # Advance game state (next player or end street)
        if not s.is_terminal:
            s = self._advance_after_action(s, action, player, opponent, deck)

        return s

    def _advance_after_action(
        self, s: GameState, action: Action, player: int, opponent: int, deck: Deck
    ) -> GameState:
        """Determine what happens next after the action."""
        if action.type in (ActionType.CHECK, ActionType.CALL):
            if s.voluntary_acted[0] and s.voluntary_acted[1]:
                # Both acted + call satisfied → street over
                s = self._start_next_street(s, deck)
            else:
                # Opponent hasn't acted yet (e.g. BB option after SB call)
                # to_call for opponent = how much more they'd need to put in
                s.to_call = max(0.0, s.street_invested[player] - s.street_invested[opponent])
                s.to_act = opponent
        elif action.type in (ActionType.BET, ActionType.RAISE):
            # Opponent must respond; to_call already set above
            if s.all_in[player] and s.all_in[opponent]:
                s = self._start_next_street(s, deck)
            else:
                s.to_act = opponent
        elif action.type == ActionType.ALL_IN:
            if s.to_call > 0:
                # Raised all-in — opponent must respond
                if s.all_in[player] and s.all_in[opponent]:
                    s = self._start_next_street(s, deck)
                else:
                    s.to_act = opponent
            else:
                # Called all-in (exact or for less) — treat like a call
                if s.voluntary_acted[0] and s.voluntary_acted[1]:
                    s = self._start_next_street(s, deck)
                else:
                    s.to_call = max(0.0, s.street_invested[player] - s.street_invested[opponent])
                    s.to_act = opponent

        return s

    # ------------------------------------------------------------------ #
    # Street management
    # ------------------------------------------------------------------ #

    def _start_next_street(self, s: GameState, deck: Deck) -> GameState:
        """Advance to the next street, dealing board cards. If no more streets, showdown."""
        if s.street == 'RIVER':
            return self._resolve_showdown(s)

        idx = STREETS.index(s.street)
        next_street = STREETS[idx + 1]

        # Deal board cards
        dealt_cards: List[Card] = []
        if next_street == 'FLOP':
            dealt_cards = deck.deal(3)
            s.board.extend(dealt_cards)
        elif next_street in ('TURN', 'RIVER'):
            dealt_cards = deck.deal(1)
            s.board.extend(dealt_cards)

        if dealt_cards:
            s.action_history.append({
                'type': 'deal_board',
                'street': next_street,
                'cards': [str(c) for c in dealt_cards],
                'board_after': [str(c) for c in s.board],
            })

        # Reset street state
        s.street = next_street
        s.street_actions = []
        s.street_invested = [0.0, 0.0]
        s.to_call = 0.0
        s.last_raise = 0.0
        s.min_raise = s.bb
        s.voluntary_acted = [False, False]

        # Postflop: non-button (BB) acts first
        s.to_act = 1 - s.button_seat

        # If someone is all-in, run out remaining streets without betting
        if any(s.all_in):
            s = self._run_out_allins(s, deck)

        return s

    def _run_out_allins(self, s: GameState, deck: Deck) -> GameState:
        """Deal remaining board cards and go straight to showdown."""
        while s.street != 'RIVER':
            idx = STREETS.index(s.street)
            s.street = STREETS[idx + 1]
            dealt_cards: List[Card] = []
            if s.street == 'FLOP' and len(s.board) < 3:
                dealt_cards = deck.deal(3 - len(s.board))
                s.board.extend(dealt_cards)
            elif s.street == 'TURN' and len(s.board) < 4:
                dealt_cards = deck.deal(4 - len(s.board))
                s.board.extend(dealt_cards)
            elif s.street == 'RIVER' and len(s.board) < 5:
                dealt_cards = deck.deal(5 - len(s.board))
                s.board.extend(dealt_cards)

            if dealt_cards:
                s.action_history.append({
                    'type': 'deal_board',
                    'street': s.street,
                    'cards': [str(c) for c in dealt_cards],
                    'board_after': [str(c) for c in s.board],
                })
        return self._resolve_showdown(s)

    def _resolve_showdown(self, s: GameState) -> GameState:
        """Evaluate both hands, award pot, mark terminal."""
        if len(s.board) < 5:
            # Should not happen in normal flow, but be safe
            pass

        score0 = evaluate_hand(s.hole_cards[0] + s.board)
        score1 = evaluate_hand(s.hole_cards[1] + s.board)
        cmp = compare_hands(score0, score1)

        s.is_terminal = True
        if cmp == 1:
            s.winner = 0
            s.pot_won = s.pot
            s.stacks[0] += s.pot
        elif cmp == -1:
            s.winner = 1
            s.pot_won = s.pot
            s.stacks[1] += s.pot
        else:
            # Split pot
            split = s.pot / 2
            s.stacks[0] += split
            s.stacks[1] += split
            s.winner = -1  # tie
            s.pot_won = split

        s.action_history.append({
            'type': 'showdown',
            'winner': s.winner,
            'pot_won': s.pot_won,
            'scores': [score0, score1],
            'board': [str(c) for c in s.board],
            'hole_cards': [[str(c) for c in hc] for hc in s.hole_cards],
        })

        return s
