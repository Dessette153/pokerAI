"""
app/logging/deal_logger.py - Per-street card dealing logger (NDJSON)

Writes a line-delimited JSON file containing only the cards that were dealt.
This is intentionally focused on dealing events (hole cards + board streets)
so it can be consumed independently from action logs.

Event types:
- hand_start
- deal_hole
- deal_board   (FLOP / TURN / RIVER)
- hand_end

File format: .ndjson (one JSON object per line)
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Optional, IO

from app.engine.state import HandResult


class DealLogger:
    def __init__(self, log_path: Optional[str] = None):
        if log_path is None:
            os.makedirs('logs', exist_ok=True)
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            log_path = f'logs/deals_{ts}.ndjson'
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
        if not self._file:
            return
        self._file.write(json.dumps(event, ensure_ascii=False) + '\n')
        self._file.flush()

    def log_hand_result(self, result: HandResult) -> None:
        """Log dealing events for a completed hand."""
        state = result.final_state

        self._write({
            'event': 'hand_start',
            'hand_id': result.hand_id,
            'button_seat': state.button_seat,
        })

        self._write({
            'event': 'deal_hole',
            'hand_id': result.hand_id,
            'hole_cards': [[str(c) for c in hc] for hc in state.hole_cards],
        })

        # Board deals are recorded by the engine in action_history as 'deal_board'
        for item in state.action_history:
            if item.get('type') == 'deal_board':
                self._write({
                    'event': 'deal_board',
                    'hand_id': result.hand_id,
                    'street': item.get('street'),
                    'cards': item.get('cards', []),
                    'board_after': item.get('board_after', []),
                })

        self._write({
            'event': 'hand_end',
            'hand_id': result.hand_id,
            'was_fold': result.was_fold,
            'winner': result.winner,
        })

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *args):
        self.close()
