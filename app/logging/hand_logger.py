"""
app/logging/hand_logger.py - JSONL format hand history event logging
"""
from __future__ import annotations
import json
import os
from datetime import datetime
from typing import Optional, IO

from app.engine.state import HandResult, GameState


class HandLogger:
    """
    Logs hand history events to a JSONL file.
    Each line is a JSON object (event).

    Event types:
    - hand_start
    - deal_hole
    - street_start
    - board_reveal
    - action_taken
    - showdown
    - hand_end
    """

    def __init__(self, log_path: Optional[str] = None):
        if log_path is None:
            os.makedirs('logs', exist_ok=True)
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            log_path = f'logs/hands_{ts}.jsonl'
        self.log_path = log_path
        self._file: Optional[IO] = None

    def open(self) -> None:
        os.makedirs(os.path.dirname(self.log_path) if os.path.dirname(self.log_path) else '.', exist_ok=True)
        self._file = open(self.log_path, 'a', encoding='utf-8')

    def close(self) -> None:
        if self._file:
            self._file.close()
            self._file = None

    def _write(self, event: dict) -> None:
        if self._file:
            self._file.write(json.dumps(event, ensure_ascii=False) + '\n')
            self._file.flush()

    def log_hand_result(self, result: HandResult) -> None:
        """Log all events for a completed hand."""
        state = result.final_state

        # hand_start
        self._write({
            'event': 'hand_start',
            'hand_id': result.hand_id,
            'button_seat': state.button_seat,
            'stacks': [snap.stacks_at_start if result.snapshots else [] for snap in result.snapshots[:1]],
        })

        # deal_hole
        self._write({
            'event': 'deal_hole',
            'hand_id': result.hand_id,
            'hole_cards': [[str(c) for c in hc] for hc in state.hole_cards],
        })

        # Per-street events
        for snap in result.snapshots:
            self._write({
                'event': 'street_start',
                'hand_id': result.hand_id,
                'street': snap.street,
                'pot': snap.pot_at_start,
                'stacks': snap.stacks_at_start,
            })

            if snap.street != 'PREFLOP' and snap.board_at_start:
                self._write({
                    'event': 'board_reveal',
                    'hand_id': result.hand_id,
                    'street': snap.street,
                    'board': [str(c) for c in snap.board_at_start],
                })

            for action in snap.actions:
                self._write({
                    'event': 'action_taken',
                    'hand_id': result.hand_id,
                    'street': snap.street,
                    'player': action.get('player'),
                    'action': action.get('type'),
                    'amount': action.get('amount', 0),
                    'pot_after': action.get('pot_after'),
                    'explanation': action.get('explanation', {}),
                })

        # Showdown
        if not result.was_fold:
            self._write({
                'event': 'showdown',
                'hand_id': result.hand_id,
                'hole_cards': [[str(c) for c in hc] for hc in state.hole_cards],
                'board': [str(c) for c in state.board],
                'winner': result.winner,
                'scores': result.showdown_scores,
            })

        # hand_end
        self._write({
            'event': 'hand_end',
            'hand_id': result.hand_id,
            'winner': result.winner,
            'pot_won': result.pot_won,
            'was_fold': result.was_fold,
            'fold_by': result.fold_by,
            'net_chips': result.net_chips,
            'final_stacks': list(state.stacks),
        })

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *args):
        self.close()
