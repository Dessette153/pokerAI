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

from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit

import config as cfg
from app.engine.engine import GameEngine
from app.engine.state import StreetSnapshot
from app.agents.ai_v1 import AIv1
from app.agents.ai_v2.ai_v2 import AIV2Agent
from app.agents.simple_agent import SimpleAgent
from app.agents.random_agent import RandomAgent
from app.agents.allin_agent import AllInAgent
from app.opponent_model.tracker import StatsTracker
from app.logging.hand_logger import HandLogger
from app.logging.deal_logger import DealLogger
from app.sim.simulator import SessionSimulator, SimEvent
from app.ui.public_state import state_to_public_dict
from app.engine.actions import Action, ActionType
from app.engine.actions import legal_actions
from app.agents.web_human_agent import WebHumanAgent
from app.agents.human_agent import validate_human_action

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
        self.mode = 'sim'                # 'sim' | 'hero'
        self.client_sid: Optional[str] = None
        self.hero_seat: Optional[int] = None
        self.human_agent: Optional[WebHumanAgent] = None
        self.stop_event = threading.Event()
        self.resume_event = threading.Event()
        self.next_event = threading.Event()  # for "next hand" from paused state
        self.current_snapshots: List[StreetSnapshot] = []
        self.current_hand_result = None
        self.simulator: Optional[SessionSimulator] = None
        self.tracker = StatsTracker()
        self.logger: Optional[HandLogger] = None
        self.deal_logger: Optional[DealLogger] = None
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

    # For hero mode we only emit to a single client.
    target_sid = sim_state.client_sid if sim_state.mode == 'hero' else None
    hero_seat = sim_state.hero_seat if sim_state.mode == 'hero' else None

    def emit_to(event: str, payload: dict):
        if target_sid:
            socketio.emit(event, payload, to=target_sid)
        else:
            socketio.emit(event, payload)

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
                    st = (
                        state_to_public_dict(event.state, hero_seat=hero_seat, reveal_all=False)
                        if target_sid and hero_seat is not None else event.state.to_dict()
                    )
                    emit_to('hand_start', {
                        'hand_id': sim.current_hand_id,
                        'state': st,
                        'agent_names': sim_state.agent_names,
                    })

                elif event.type == 'action':
                    st = (
                        state_to_public_dict(event.state, hero_seat=hero_seat, reveal_all=False)
                        if target_sid and hero_seat is not None else event.state.to_dict()
                    )
                    emit_to('game_state', {
                        'hand_id': sim.current_hand_id,
                        'state': st,
                        'last_action': event.action,
                        'stats': sim_state.tracker.to_dict(),
                    })
                    # Small delay so UI can render
                    time.sleep(sim_state.action_delay)

                elif event.type == 'street':
                    snapshots_this_hand = [_snapshot_to_dict(s) for s in event.snapshots]
                    st = (
                        state_to_public_dict(event.state, hero_seat=hero_seat, reveal_all=False)
                        if target_sid and hero_seat is not None else event.state.to_dict()
                    )
                    emit_to('street_change', {
                        'hand_id': sim.current_hand_id,
                        'street': event.street,
                        'state': st,
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
                    if sim_state.deal_logger:
                        sim_state.deal_logger.log_hand_result(result)

                    # Update simulator state
                    sim.record_result(result)

                    if event.was_fold:
                        # Fold: emit and briefly pause, then continue
                        st = (
                            state_to_public_dict(event.state, hero_seat=hero_seat, reveal_all=True)
                            if target_sid and hero_seat is not None else event.state.to_dict(reveal_all=True)
                        )
                        emit_to('hand_ended', {
                            'hand_id': result.hand_id,
                            'was_fold': True,
                            'fold_by': result.fold_by,
                            'winner': result.winner,
                            'pot_won': result.pot_won,
                            'net_chips': result.net_chips,
                            'state': st,
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

                        st = (
                            state_to_public_dict(event.state, hero_seat=hero_seat, reveal_all=True)
                            if target_sid and hero_seat is not None else event.state.to_dict(reveal_all=True)
                        )
                        emit_to('paused', {
                            'hand_id': result.hand_id,
                            'was_fold': False,
                            'winner': result.winner,
                            'pot_won': result.pot_won,
                            'net_chips': result.net_chips,
                            'state': st,
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
            emit_to('error', {'message': str(e)})
            import traceback
            traceback.print_exc()

        if sim_state.stop_event.is_set():
            break

    sim_state.running = False
    emit_to('sim_stopped', {})


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

    payload = (data or {})
    opponent_type = payload.get('opponent', 'simple')
    ai_version = payload.get('ai', 'v1')

    # Build engine and agents
    engine = GameEngine(sb=cfg.SB, bb=cfg.BB)
    if ai_version == 'v2':
        ai_agent = AIV2Agent(name='AI v2', seat=0)
    else:
        ai_agent = AIv1(name='AI v1', seat=0)

    if opponent_type == 'random':
        opp_agent = RandomAgent(name='Random')
    elif opponent_type == 'allin':
        opp_agent = AllInAgent(name='All-In')
    elif opponent_type == 'ai_v1':
        opp_agent = AIv1(name='AI v1 (Opp)')
    elif opponent_type == 'ai_v2':
        opp_agent = AIV2Agent(name='AI v2 (Opp)', seat=1)
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
    sim_state.mode = 'sim'
    sim_state.client_sid = None
    sim_state.hero_seat = None
    sim_state.human_agent = None
    sim_state.stop_event.clear()
    sim_state.resume_event.clear()
    sim_state.next_event.clear()

    # Start background logger
    sim_state.logger = HandLogger()
    sim_state.logger.open()

    # Start dealing logger (hole + per-street board deals)
    sim_state.deal_logger = DealLogger()
    sim_state.deal_logger.open()

    # Launch background thread
    sim_state.bg_thread = threading.Thread(target=_simulation_loop, daemon=True)
    sim_state.bg_thread.start()

    emit('sim_started', {'agent_names': sim_state.agent_names})


@socketio.on('start_hero')
def on_start_hero(data=None):
    """Start an interactive Hero vs AI session for the connected client."""
    if sim_state.running:
        emit('error', {'message': 'Simulation already running'})
        return

    payload = (data or {})
    hero_seat = int(payload.get('hero_seat', 0))
    if hero_seat not in (0, 1):
        emit('error', {'message': 'hero_seat must be 0 or 1'})
        return
    villain_kind = payload.get('villain', 'v2')

    sid = request.sid

    engine = GameEngine(sb=cfg.SB, bb=cfg.BB)

    def prompt_fn(gs):
        # Emit a dedicated prompt event so the browser can show action buttons.
        pub = state_to_public_dict(gs, hero_seat=hero_seat, reveal_all=False)
        la = [a.value for a in legal_actions(gs)]
        socketio.emit('hero_turn', {
            'hand_id': gs.hand_id,
            'hero_seat': hero_seat,
            'state': pub,
            'legal_actions': la,
        }, to=sid)

    hero_agent = WebHumanAgent(name='Hero', seat=hero_seat, prompt_fn=prompt_fn)
    villain_seat = 1 - hero_seat
    if villain_kind == 'v2':
        villain_agent = AIV2Agent(name='AI v2', seat=villain_seat)
    elif villain_kind == 'v1':
        villain_agent = AIv1(name='AI v1', seat=villain_seat)
    elif villain_kind == 'simple':
        villain_agent = SimpleAgent(name='Simple')
    elif villain_kind == 'random':
        villain_agent = RandomAgent(name='Random')
    elif villain_kind == 'allin':
        villain_agent = AllInAgent(name='All-In')
    else:
        emit('error', {'message': f'Unknown villain: {villain_kind}'})
        return

    agents = [None, None]
    agents[hero_seat] = hero_agent
    agents[villain_seat] = villain_agent

    sim_state.agent_names = [
        hero_agent.name if hero_seat == 0 else villain_agent.name,
        hero_agent.name if hero_seat == 1 else villain_agent.name,
    ]

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
    sim_state.mode = 'hero'
    sim_state.client_sid = sid
    sim_state.hero_seat = hero_seat
    sim_state.human_agent = hero_agent
    sim_state.stop_event.clear()
    sim_state.resume_event.clear()
    sim_state.next_event.clear()

    sim_state.logger = HandLogger()
    sim_state.logger.open()
    sim_state.deal_logger = DealLogger()
    sim_state.deal_logger.open()

    sim_state.bg_thread = threading.Thread(target=_simulation_loop, daemon=True)
    sim_state.bg_thread.start()

    emit('sim_started', {'agent_names': sim_state.agent_names})


@socketio.on('hero_action')
def on_hero_action(data):
    """Receive a hero action from the browser and unblock WebHumanAgent."""
    if not sim_state.running or sim_state.mode != 'hero' or sim_state.human_agent is None:
        emit('hero_action_error', {'message': 'No hero session running'})
        return

    if request.sid != sim_state.client_sid:
        emit('hero_action_error', {'message': 'This session belongs to another client'})
        return

    agent = sim_state.human_agent
    if not agent.waiting_for_action:
        emit('hero_action_error', {'message': 'Not currently waiting for an action'})
        return

    pending_state = agent.pending_state
    if pending_state is None:
        emit('hero_action_error', {'message': 'No pending state'})
        return

    try:
        t = (data or {}).get('type')
        if not t:
            raise ValueError('Missing action type')
        t = str(t).lower().replace('-', '_')
        at = ActionType(t)
        amt = float((data or {}).get('amount') or 0.0)
        action = Action(type=at, amount=amt)
        validate_human_action(action, pending_state)
    except Exception as e:
        emit('hero_action_error', {'message': str(e)})
        return

    agent.set_action(action)
    emit('hero_action_ok', {})


@socketio.on('stop_sim')
def on_stop_sim():
    """Stop the simulation."""
    sim_state.stop_event.set()
    sim_state.resume_event.set()   # unblock any waiting
    sim_state.next_event.set()
    # Unblock any pending hero action wait
    if sim_state.human_agent is not None:
        try:
            ps = sim_state.human_agent.pending_state
            if ps is not None:
                la = legal_actions(ps)
                if ActionType.CHECK in la:
                    sim_state.human_agent.set_action(Action(ActionType.CHECK))
                elif ActionType.CALL in la:
                    sim_state.human_agent.set_action(Action(ActionType.CALL))
                elif ActionType.FOLD in la:
                    sim_state.human_agent.set_action(Action(ActionType.FOLD))
        except Exception:
            pass
    if sim_state.logger:
        sim_state.logger.close()
        sim_state.logger = None
    if sim_state.deal_logger:
        sim_state.deal_logger.close()
        sim_state.deal_logger = None
    sim_state.mode = 'sim'
    sim_state.client_sid = None
    sim_state.hero_seat = None
    sim_state.human_agent = None
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
