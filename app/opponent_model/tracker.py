"""
app/opponent_model/tracker.py - VPIP, PFR, AF statistics tracker
"""
from __future__ import annotations
from typing import Dict, Optional


class PlayerStats:
    """Per-player statistics tracker."""
    def __init__(self):
        self.hands_dealt = 0

        # VPIP: Voluntarily Put money In Pot (preflop call/raise)
        self.vpip_opportunities = 0
        self.vpip_count = 0

        # PFR: Pre-Flop Raise
        self.pfr_opportunities = 0
        self.pfr_count = 0

        # AF: Aggression Factor = (bets + raises) / calls
        self.total_bets_raises = 0
        self.total_calls = 0

        # Win/loss tracking
        self.net_chips = 0.0
        self.wins = 0
        self.losses = 0
        self.splits = 0

    @property
    def vpip(self) -> float:
        if self.vpip_opportunities == 0:
            return 0.0
        return self.vpip_count / self.vpip_opportunities

    @property
    def pfr(self) -> float:
        if self.pfr_opportunities == 0:
            return 0.0
        return self.pfr_count / self.pfr_opportunities

    @property
    def af(self) -> float:
        if self.total_calls == 0:
            return float(self.total_bets_raises) if self.total_bets_raises > 0 else 0.0
        return self.total_bets_raises / self.total_calls

    def to_dict(self) -> dict:
        return {
            'hands_dealt': self.hands_dealt,
            'vpip': round(self.vpip * 100, 1),
            'pfr': round(self.pfr * 100, 1),
            'af': round(self.af, 2),
            'net_chips': round(self.net_chips, 1),
            'wins': self.wins,
            'losses': self.losses,
            'splits': self.splits,
            'win_rate': round(self.wins / max(1, self.hands_dealt) * 100, 1),
        }


class StatsTracker:
    """Tracks statistics for both players across multiple hands."""

    def __init__(self):
        self.players: Dict[int, PlayerStats] = {0: PlayerStats(), 1: PlayerStats()}
        self.total_hands = 0
        self.bb = 100.0

    def record_hand(self, hand_result) -> None:
        """Update stats from a completed HandResult."""
        from app.engine.state import HandResult
        self.total_hands += 1

        for seat in (0, 1):
            stats = self.players[seat]
            stats.hands_dealt += 1

            # Net chips
            stats.net_chips += hand_result.net_chips[seat]

            # Win/loss/split
            if hand_result.winner == seat:
                stats.wins += 1
            elif hand_result.winner == -1:
                stats.splits += 1
            else:
                stats.losses += 1

        # Walk through action history for VPIP/PFR/AF
        is_preflop = True
        preflop_seen = {0: False, 1: False}

        for action_dict in hand_result.final_state.action_history:
            if action_dict.get('type') == 'showdown':
                continue

            # Detect street changes
            # We use action history which doesn't have explicit street markers
            # Use snapshots to determine street from actions
            player = action_dict.get('player')
            action_type = action_dict.get('type')

            if player is None:
                continue

            stats = self.players[player]
            street = self._get_action_street(action_dict, hand_result)

            if street == 'PREFLOP':
                # VPIP: did player voluntarily put $ in preflop?
                if not preflop_seen[player]:
                    stats.vpip_opportunities += 1
                    stats.pfr_opportunities += 1
                    preflop_seen[player] = True

                if action_type in ('call', 'raise', 'bet'):
                    if not hasattr(stats, f'_vpip_done_{hand_result.hand_id}_{player}'):
                        setattr(stats, f'_vpip_done_{hand_result.hand_id}_{player}', True)
                        stats.vpip_count += 1
                if action_type in ('raise', 'bet'):
                    if not hasattr(stats, f'_pfr_done_{hand_result.hand_id}_{player}'):
                        setattr(stats, f'_pfr_done_{hand_result.hand_id}_{player}', True)
                        stats.pfr_count += 1

            # AF tracking (all streets)
            if action_type in ('bet', 'raise'):
                stats.total_bets_raises += 1
            elif action_type == 'call':
                stats.total_calls += 1

    def _get_action_street(self, action_dict: dict, hand_result) -> str:
        """Determine which street an action occurred on using snapshots."""
        # Match action to snapshot by position in action_history
        for snap in hand_result.snapshots:
            for a in snap.actions:
                if a is action_dict or a == action_dict:
                    return snap.street
        return 'PREFLOP'

    def bb_per_100(self, seat: int) -> float:
        """bb/100 hands win rate."""
        if self.total_hands == 0:
            return 0.0
        bb = self.bb if self.bb > 0 else 100.0
        return (self.players[seat].net_chips / bb) / self.total_hands * 100

    def to_dict(self) -> dict:
        return {
            'total_hands': self.total_hands,
            'player0': self.players[0].to_dict(),
            'player1': self.players[1].to_dict(),
            'bb_per_100_p0': round(self.bb_per_100(0), 2),
            'bb_per_100_p1': round(self.bb_per_100(1), 2),
        }
