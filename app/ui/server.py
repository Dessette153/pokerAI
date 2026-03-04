"""
app/ui/server.py - Flask + SocketIO UI server

Simulation state machine:
  IDLE     → start_sim → RUNNING
  RUNNING  → fold ends → RUNNING (fast continue after brief pause)
  RUNNING  → showdown  → PAUSED
  PAUSED   → resume    → RUNNING
  PAUSED   → next_hand → RUNNING
  RUNNING  → stop_sim  → IDLE
"""
from __future__ import annotations
import threading
import time
from typing import Optional, List, Dict

from flask import Flask, render_template
from flask_socketio import SocketIO, emit

import config as cfg
from app.engine.engine import GameEngine
from app.engine.state import StreetSnapshot
from app.agents.ai_v1 import AIv1
from app.agents.simple_agent import SimpleAgent
from app.agents.random_agent import RandomAgent
from app.agents.allin_agent import AllInAgent
from app.opponent_model.tracker import StatsTracker
from app.logging.hand_logger import HandLogger
from app.sim.simulator import SessionSimulator, SimEvent

app = Flask(__name__, template_folder='templates', static_folder='static')
app.config['SECRET_KEY'] = 'pokerai-secret'
socketio = SocketIO(app, cors_allowed_origins='*', async_mode='threading')

# ------------------------------------------------------------------ #
# Global simulation state
# ------------------------------------------------------------------ #

class SimState:
    def __init__(self):
        self.running = False
        self.paused = False              # True when waiting at showdown
        self.stop_event = threading.Event()
        self.resume_event = threading.Event()
        self.next_event = threading.Event()  # for "next hand" from paused state
        self.current_snapshots: List[StreetSnapshot] = []
        self.current_hand_result = None
        self.simulator: Optional[SessionSimulator] = None
        self.tracker = StatsTracker()
        self.logger: Optional[HandLogger] = None
        self.bg_thread: Optional[threading.Thread] = None
        self.lock = threading.Lock()
        self.agent_names = [cfg.SEAT_NAMES[0], cfg.SEAT_NAMES[1]]
        self.action_delay: float = 1.0 / 3   # default: 3x speed ≈ 0.33s/action

sim_state = SimState()


# ------------------------------------------------------------------ #
# Helper: serialize snapshot for sending over WebSocket
# ------------------------------------------------------------------ #

def _snapshot_to_dict(snap: StreetSnapshot) -> dict:
    return {
        'street': snap.street,
        'board_at_start': [c.to_dict() for c in snap.board_at_start],
        'stacks_at_start': snap.stacks_at_start,
        'pot_at_start': snap.pot_at_start,
        'actions': snap.actions,
        'state_at_start': snap.state_at_start.to_dict(reveal_all=True),
        'state_at_end': snap.state_at_end.to_dict(reveal_all=True) if snap.state_at_end else None,
    }


# ------------------------------------------------------------------ #
# Background simulation thread
# ------------------------------------------------------------------ #

def _simulation_loop():
    """Main simulation loop running in a background thread."""
    sim = sim_state.simulator

    while not sim_state.stop_event.is_set():
        # Get the generator for the next hand
        gen = sim.next_hand_generator()

        # Process events from this hand
        try:
            snapshots_this_hand: List[StreetSnapshot] = []

            for event in gen:
                if sim_state.stop_event.is_set():
                    break

                if event.type == 'hand_start':
                    socketio.emit('hand_start', {
                        'hand_id': sim.current_hand_id,
                        'state': event.state.to_dict(),
                        'agent_names': sim_state.agent_names,
                    })

                elif event.type == 'action':
                    socketio.emit('game_state', {
                        'hand_id': sim.current_hand_id,
                        'state': event.state.to_dict(),
                        'last_action': event.action,
                        'stats': sim_state.tracker.to_dict(),
                    })
                    # Small delay so UI can render
                    time.sleep(sim_state.action_delay)

                elif event.type == 'street':
                    snapshots_this_hand = [_snapshot_to_dict(s) for s in event.snapshots]
                    socketio.emit('street_change', {
                        'hand_id': sim.current_hand_id,
                        'street': event.street,
                        'state': event.state.to_dict(),
                        'snapshots': snapshots_this_hand,
                    })
                    time.sleep(min(0.3, sim_state.action_delay * 1.5))

                elif event.type == 'hand_end':
                    result = event.result
                    snapshots_this_hand = [_snapshot_to_dict(s) for s in event.snapshots]

                    # Record result in tracker
                    sim_state.tracker.record_hand(result)
                    if sim_state.logger:
                        sim_state.logger.log_hand_result(result)

                    # Update simulator state
                    sim.record_result(result)

                    if event.was_fold:
                        # Fold: emit and briefly pause, then continue
                        socketio.emit('hand_ended', {
                            'hand_id': result.hand_id,
                            'was_fold': True,
                            'fold_by': result.fold_by,
                            'winner': result.winner,
                            'pot_won': result.pot_won,
                            'net_chips': result.net_chips,
                            'state': event.state.to_dict(reveal_all=True),
                            'snapshots': snapshots_this_hand,
                            'stats': sim_state.tracker.to_dict(),
                        })
                        time.sleep(cfg.FOLD_PAUSE_MS / 1000.0)
                    else:
                        # Showdown: pause until user resumes
                        sim_state.current_snapshots = event.snapshots
                        sim_state.current_hand_result = result
                        sim_state.paused = True
                        sim_state.resume_event.clear()
                        sim_state.next_event.clear()

                        socketio.emit('paused', {
                            'hand_id': result.hand_id,
                            'was_fold': False,
                            'winner': result.winner,
                            'pot_won': result.pot_won,
                            'net_chips': result.net_chips,
                            'state': event.state.to_dict(reveal_all=True),
                            'snapshots': snapshots_this_hand,
                            'stats': sim_state.tracker.to_dict(),
                        })

                        # Wait for resume or next_hand signal
                        while not sim_state.stop_event.is_set():
                            if sim_state.resume_event.is_set() or sim_state.next_event.is_set():
                                break
                            time.sleep(0.05)

                        sim_state.paused = False

        except StopIteration:
            pass
        except Exception as e:
            socketio.emit('error', {'message': str(e)})
            import traceback
            traceback.print_exc()

        if sim_state.stop_event.is_set():
            break

    sim_state.running = False
    socketio.emit('sim_stopped', {})


# ------------------------------------------------------------------ #
# Routes
# ------------------------------------------------------------------ #

@app.route('/')
def index():
    return render_template('index.html')


# ------------------------------------------------------------------ #
# SocketIO event handlers
# ------------------------------------------------------------------ #

@socketio.on('connect')
def on_connect():
    emit('connected', {
        'message': 'Connected to Poker AI server',
        'config': {
            'sb': cfg.SB,
            'bb': cfg.BB,
            'starting_stack': cfg.STARTING_STACK,
        }
    })


@socketio.on('start_sim')
def on_start_sim(data=None):
    """Start a new simulation session."""
    if sim_state.running:
        emit('error', {'message': 'Simulation already running'})
        return

    opponent_type = (data or {}).get('opponent', 'simple')

    # Build engine and agents
    engine = GameEngine(sb=cfg.SB, bb=cfg.BB)
    ai_agent = AIv1(name='AI v1', seat=0)

    if opponent_type == 'random':
        opp_agent = RandomAgent(name='Random')
    elif opponent_type == 'allin':
        opp_agent = AllInAgent(name='All-In')
    else:
        opp_agent = SimpleAgent(name='Simple')

    agents = [ai_agent, opp_agent]
    sim_state.agent_names = [ai_agent.name, opp_agent.name]

    simulator = SessionSimulator(
        engine=engine,
        agents=agents,
        starting_stacks=[cfg.STARTING_STACK, cfg.STARTING_STACK],
        rebuy_to=cfg.STARTING_STACK,
        rebuy_both=True,
    )

    sim_state.simulator = simulator
    sim_state.tracker = StatsTracker()
    sim_state.tracker.bb = cfg.BB
    sim_state.running = True
    sim_state.paused = False
    sim_state.stop_event.clear()
    sim_state.resume_event.clear()
    sim_state.next_event.clear()

    # Start background logger
    sim_state.logger = HandLogger()
    sim_state.logger.open()

    # Launch background thread
    sim_state.bg_thread = threading.Thread(target=_simulation_loop, daemon=True)
    sim_state.bg_thread.start()

    emit('sim_started', {'agent_names': sim_state.agent_names})


@socketio.on('stop_sim')
def on_stop_sim():
    """Stop the simulation."""
    sim_state.stop_event.set()
    sim_state.resume_event.set()   # unblock any waiting
    sim_state.next_event.set()
    if sim_state.logger:
        sim_state.logger.close()
        sim_state.logger = None
    emit('sim_stopping', {})


@socketio.on('resume')
def on_resume():
    """Resume simulation after a showdown pause."""
    if sim_state.paused:
        sim_state.resume_event.set()
        emit('resuming', {})


@socketio.on('next_hand')
def on_next_hand():
    """Skip to next hand while paused."""
    if sim_state.paused:
        sim_state.next_event.set()
        emit('resuming', {})


@socketio.on('revert_to_street')
def on_revert_to_street(data):
    """
    Return the game state snapshot for a specific street of the current hand.
    Used for post-showdown navigation.
    """
    street = data.get('street', 'PREFLOP')
    snapshots = sim_state.current_snapshots

    target_snap = None
    for snap in snapshots:
        if snap.street == street:
            target_snap = snap
            break

    if target_snap is None:
        emit('error', {'message': f'Street {street} not found in current hand'})
        return

    emit('street_view', {
        'street': street,
        'snapshot': _snapshot_to_dict(target_snap),
        'state': target_snap.state_at_start.to_dict(reveal_all=True),
    })


@socketio.on('get_stats')
def on_get_stats():
    emit('stats_update', sim_state.tracker.to_dict())


@socketio.on('set_speed')
def on_set_speed(data):
    """Adjust simulation speed. value=1..20, delay = 1.0 / value seconds."""
    val = max(1, min(20, int(data.get('value', 3))))
    sim_state.action_delay = 1.0 / val


if __name__ == '__main__':
    socketio.run(app, host=cfg.UI_HOST, port=cfg.UI_PORT, debug=False)
