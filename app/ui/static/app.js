/**
 * app.js - Poker AI Simulator Frontend
 * Connects to Flask-SocketIO backend and renders the game state.
 */

const socket = io();

// ---- State ----
let gameState  = null;
let isPaused   = false;
let currentSnapshots = [];
let agentNames = ['AI v1', 'Opponent'];
let visitedStreets = new Set();
let uiMode = 'sim';
let heroSeat = 0;

// ---- DOM refs ----
const $ = id => document.getElementById(id);
const btnStart    = $('btn-start');
const btnStop     = $('btn-stop');
const simStatus   = $('sim-status');
const handCounter = $('hand-counter');
const actionLog   = $('action-log');
const streetNav   = $('street-nav');
const pauseCtrl   = $('pause-controls');
const potAmount   = $('pot-amount');
const curStreet   = $('cur-street');
const curPot      = $('cur-pot');
const curTocall   = $('cur-tocall');

// Hero controls
const modeSelect = $('mode-select');
const aiSelect = $('ai-select');
const opponentSelect = $('opponent-select');
const heroSeatSelect = $('hero-seat-select');
const villainSelect = $('villain-select');

const heroControls = $('hero-controls');
const heroError = $('hero-error');
const heroAmount = $('hero-amount');
const btnHeroFold = $('btn-hero-fold');
const btnHeroCheck = $('btn-hero-check');
const btnHeroCall = $('btn-hero-call');
const btnHeroBet = $('btn-hero-bet');
const btnHeroRaise = $('btn-hero-raise');
const btnHeroAllin = $('btn-hero-allin');

// ---- Helpers ----

function suitSymbol(suit) {
  // suit: 0=clubs, 1=diamonds, 2=hearts, 3=spades
  return ['♣', '♦', '♥', '♠'][suit] || '?';
}

function isRed(suit) { return suit === 1 || suit === 2; }

function makeCardEl(cardData) {
  if (!cardData || cardData.rank === 0) {
    const el = document.createElement('div');
    el.className = 'card face-down';
    el.textContent = '?';
    return el;
  }
  const el = document.createElement('div');
  el.className = 'card' + (isRed(cardData.suit) ? ' red-card' : '');
  el.innerHTML = `<span class="rank">${cardData.str ? cardData.str.slice(0,-1) : '?'}</span><span class="suit">${suitSymbol(cardData.suit)}</span>`;
  return el;
}

function renderCards(containerId, cardsData, isWinner = false) {
  const container = $(containerId);
  container.innerHTML = '';
  (cardsData || []).forEach(cd => {
    const el = makeCardEl(cd);
    if (isWinner && cd.rank !== 0) el.classList.add('winner-card');
    container.appendChild(el);
  });
}

function renderBoard(boardCards) {
  const container = $('board-cards');
  container.innerHTML = '';
  for (let i = 0; i < 5; i++) {
    if (i < boardCards.length) {
      container.appendChild(makeCardEl(boardCards[i]));
    } else {
      const ph = document.createElement('div');
      ph.className = 'card-placeholder';
      ph.textContent = '-';
      container.appendChild(ph);
    }
  }
}

function fmt(n) {
  if (n === undefined || n === null) return '-';
  return Math.round(n).toLocaleString();
}

function setStatus(text, cls) {
  simStatus.textContent = text;
  simStatus.className = `status-${cls}`;
}

function addLog(text, cls = 'info') {
  const entry = document.createElement('div');
  entry.className = `log-entry log-${cls}`;
  entry.textContent = text;
  actionLog.appendChild(entry);
  actionLog.scrollTop = actionLog.scrollHeight;
  // Keep log at max 200 entries
  while (actionLog.children.length > 200) {
    actionLog.removeChild(actionLog.firstChild);
  }
}

function clearLog() {
  actionLog.innerHTML = '';
}

function actionTypeClass(type) {
  const m = {fold:'fold', check:'check', call:'call', bet:'bet', raise:'raise', all_in:'all_in'};
  return m[type] || 'info';
}

function showBadge(playerId, text, cls) {
  const el = $(`p${playerId}-action-badge`);
  el.textContent = text;
  el.className = `action-badge badge-${cls}`;
  setTimeout(() => { el.textContent = ''; el.className = 'action-badge'; }, 2000);
}

function showBetDisplay(playerId, amount) {
  const el = $(`p${playerId}-bet-display`);
  if (amount > 0) {
    el.textContent = `💰 ${fmt(amount)}`;
  } else {
    el.textContent = '';
  }
}

// ---- Render full game state ----

function renderGameState(state, revealAll = false) {
  if (!state) return;
  gameState = state;

  // Pot
  potAmount.textContent = fmt(state.pot);
  curStreet.textContent  = state.street || '-';
  curPot.textContent     = fmt(state.pot);
  curTocall.textContent  = fmt(state.to_call);
  handCounter.textContent = `Hand #${state.hand_id || 0}`;

  // Stacks
  $('p0-stack').textContent = fmt(state.stacks[0]);
  $('p1-stack').textContent = fmt(state.stacks[1]);

  // Dealer button
  const btn = state.button_seat;
  $('p0-dealer').style.display = (btn === 0) ? 'inline' : 'none';
  $('p1-dealer').style.display = (btn === 1) ? 'inline' : 'none';

  // Actor highlight
  $('player0-area').classList.toggle('acting', state.to_act === 0 && !state.is_terminal);
  $('player1-area').classList.toggle('acting', state.to_act === 1 && !state.is_terminal);

  // Board
  renderBoard(state.board || []);

  // Hole cards
  const hc = state.hole_cards || [[], []];
  renderCards('p0-cards', hc[0] || [], state.winner === 0);
  renderCards('p1-cards', hc[1] || [], state.winner === 1);
}

// ---- Update stats panel ----

function updateStats(stats) {
  if (!stats) return;
  const p0 = stats.player0 || {};
  const p1 = stats.player1 || {};

  $('s0-hands').textContent  = p0.hands_dealt || 0;
  $('s0-win').textContent    = `${p0.win_rate || 0}%`;
  $('s0-vpip').textContent   = `${p0.vpip || 0}%`;
  $('s0-pfr').textContent    = `${p0.pfr || 0}%`;
  $('s0-af').textContent     = p0.af || '0.0';
  $('s0-bb100').textContent  = stats.bb_per_100_p0 || '0.0';
  const net0 = p0.net_chips || 0;
  $('s0-net').textContent    = (net0 >= 0 ? '+' : '') + fmt(net0);
  $('s0-net').style.color    = net0 >= 0 ? '#2ecc71' : '#e74c3c';

  $('s1-hands').textContent  = p1.hands_dealt || 0;
  $('s1-win').textContent    = `${p1.win_rate || 0}%`;
  $('s1-vpip').textContent   = `${p1.vpip || 0}%`;
  $('s1-pfr').textContent    = `${p1.pfr || 0}%`;
  $('s1-af').textContent     = p1.af || '0.0';
  $('s1-bb100').textContent  = stats.bb_per_100_p1 || '0.0';
  const net1 = p1.net_chips || 0;
  $('s1-net').textContent    = (net1 >= 0 ? '+' : '') + fmt(net1);
  $('s1-net').style.color    = net1 >= 0 ? '#2ecc71' : '#e74c3c';
}

// ---- Update AI decision panel ----

function updateAIDecision(action) {
  if (!action) return;
  const expl = action.explanation || {};
  const player = action.player;

  // In sim mode we show player 0 decisions. In hero mode, show non-hero seat decisions.
  if (uiMode === 'hero') {
    if (player === heroSeat) return;
  } else {
    if (player !== 0) return;
  }

  const type = action.type;
  const amount = action.amount;

  $('ai-action').textContent = type.toUpperCase().replace('_', ' ') + (amount > 0 ? ` ${fmt(amount)}` : '');
  $('ai-action').style.color = {fold:'#ff8a8a',check:'#6dff6d',call:'#6ab4ff',bet:'#ffc940',raise:'#ff80e0',all_in:'#ff6600'}[type] || '#ccc';
  const equity = (expl.equity !== undefined) ? expl.equity : expl.equity_vs_range;
  $('ai-equity').textContent = equity !== undefined ? `${(equity * 100).toFixed(1)}%` : '-';
  $('ai-potodds').textContent = expl.pot_odds !== undefined ? `${(expl.pot_odds * 100).toFixed(1)}%` : '-';
  $('ai-tier').textContent   = expl.tier || '-';
  $('ai-reasoning').textContent = expl.reasoning || expl.reason || '-';
}

function setMode(mode) {
  uiMode = mode;
  const isHero = (mode === 'hero');
  // Toggle config selects
  aiSelect.style.display = isHero ? 'none' : 'inline-block';
  opponentSelect.style.display = isHero ? 'none' : 'inline-block';
  heroSeatSelect.style.display = isHero ? 'inline-block' : 'none';
  villainSelect.style.display = isHero ? 'inline-block' : 'none';
  // Hide hero controls until prompted
  heroControls.style.display = 'none';
  heroError.textContent = '';
}

function setHeroControlsEnabled(enabled) {
  [btnHeroFold, btnHeroCheck, btnHeroCall, btnHeroBet, btnHeroRaise, btnHeroAllin, heroAmount]
    .forEach(el => { if (el) el.disabled = !enabled; });
}

function showHeroError(msg) {
  heroError.textContent = msg || '';
}

function normalizeLegal(legalActions) {
  const s = new Set();
  (legalActions || []).forEach(a => s.add(String(a)));
  return s;
}

function updateHeroControlsFromPrompt(prompt) {
  if (!prompt || !prompt.state) return;
  heroSeat = prompt.hero_seat ?? heroSeat;
  const st = prompt.state;
  const legal = normalizeLegal(prompt.legal_actions);

  // Update call/check labels with amounts when relevant
  const toCall = st.to_call ?? 0;
  const minRaise = st.min_raise ?? 0;

  btnHeroFold.style.display = legal.has('fold') ? 'inline-block' : 'none';
  btnHeroCheck.style.display = legal.has('check') ? 'inline-block' : 'none';
  btnHeroCall.style.display = legal.has('call') ? 'inline-block' : 'none';
  btnHeroAllin.style.display = legal.has('all_in') ? 'inline-block' : 'none';

  btnHeroCall.textContent = toCall > 0 ? `Call ${fmt(toCall)}` : 'Call';
  btnHeroCheck.textContent = 'Check';

  const canBet = legal.has('bet');
  const canRaise = legal.has('raise');
  btnHeroBet.style.display = canBet ? 'inline-block' : 'none';
  btnHeroRaise.style.display = canRaise ? 'inline-block' : 'none';

  heroAmount.style.display = (canBet || canRaise) ? 'inline-block' : 'none';
  heroAmount.placeholder = (canRaise ? `Raise (min ${fmt(minRaise)})` : `Bet (min ${fmt(minRaise)})`);

  showHeroError('');
  setHeroControlsEnabled(true);
  heroControls.style.display = 'flex';
}

function sendHeroAction(type) {
  const payload = { type };
  if (type === 'bet' || type === 'raise') {
    const v = heroAmount.value;
    if (!v) {
      showHeroError('Amount required for bet/raise');
      return;
    }
    payload.amount = parseFloat(v);
  }

  setHeroControlsEnabled(false);
  showHeroError('');
  socket.emit('hero_action', payload);
}

// ---- Street navigation ----

function updateStreetNav(snapshots) {
  currentSnapshots = snapshots || [];
  visitedStreets = new Set(snapshots.map(s => s.street));

  const streets = ['PREFLOP','FLOP','TURN','RIVER'];
  streets.forEach(st => {
    const btn = document.querySelector(`[data-street="${st}"]`);
    if (btn) {
      btn.disabled = !visitedStreets.has(st);
      btn.classList.remove('active');
    }
  });
}

function setActiveStreet(street) {
  document.querySelectorAll('[data-street]').forEach(btn => btn.classList.remove('active'));
  const btn = document.querySelector(`[data-street="${street}"]`);
  if (btn) btn.classList.add('active');
}

// ---- Pause / Resume logic ----

function enterPauseMode(data) {
  isPaused = true;
  setStatus('● PAUSED', 'paused');
  streetNav.style.display = 'flex';
  pauseCtrl.style.display = 'flex';

  currentSnapshots = data.snapshots || [];
  updateStreetNav(data.snapshots);

  // Show the "RIVER" (final) state as active
  if (visitedStreets.has('RIVER')) setActiveStreet('RIVER');
  else if (visitedStreets.has('TURN')) setActiveStreet('TURN');
  else if (visitedStreets.has('FLOP')) setActiveStreet('FLOP');
  else setActiveStreet('PREFLOP');
}

function exitPauseMode() {
  isPaused = false;
  streetNav.style.display = 'none';
  pauseCtrl.style.display = 'none';
  document.querySelectorAll('[data-street]').forEach(btn => btn.classList.remove('active'));
}

// ---- Show overlay briefly ----

function showOverlay(title, detail, duration = 1500) {
  $('overlay-title').textContent = title;
  $('overlay-detail').textContent = detail;
  $('showdown-overlay').style.display = 'flex';
  setTimeout(() => {
    $('showdown-overlay').style.display = 'none';
  }, duration);
}

// ---- Global button actions ----

function resumeSim() {
  socket.emit('resume');
  exitPauseMode();
  setStatus('● RUNNING', 'running');
}

function nextHand() {
  socket.emit('next_hand');
  exitPauseMode();
  setStatus('● RUNNING', 'running');
}

function revertToStreet(street) {
  socket.emit('revert_to_street', { street });
  setActiveStreet(street);
}

// ---- Button handlers ----

btnStart.addEventListener('click', () => {
  const mode = modeSelect.value || 'sim';
  if (mode === 'hero') {
    const hs = parseInt(heroSeatSelect.value);
    const villain = villainSelect.value;
    socket.emit('start_hero', { hero_seat: hs, villain });
  } else {
    const opponent = opponentSelect.value;
    const ai = aiSelect ? aiSelect.value : 'v1';
    socket.emit('start_sim', { opponent, ai });
  }
});

btnStop.addEventListener('click', () => {
  socket.emit('stop_sim');
  exitPauseMode();
  btnStart.disabled = false;
  btnStop.disabled = true;
  setStatus('● STOPPED', 'stopped');
});

// ---- Speed slider ----
// delay = 1.0 / sliderVal  (val=1→1s, val=3→0.33s, val=10→0.1s, val=20→0.05s)
const speedSlider = $('speed-slider');
const speedDisplay = $('speed-display');

function applySpeed(val) {
  const v = parseInt(val);
  speedDisplay.textContent = v >= 20 ? 'Max' : `${v}x`;
  socket.emit('set_speed', { value: v });
}

speedSlider.addEventListener('input', () => applySpeed(speedSlider.value));

// ---- SocketIO Event Handlers ----

socket.on('connected', data => {
  addLog('Connected to Poker AI server', 'info');
});

socket.on('sim_started', data => {
  agentNames = data.agent_names || ['AI v1', 'Opponent'];
  $('p0-name').textContent = agentNames[0];
  $('p1-name').textContent = agentNames[1];
  $('stats-p0-name').textContent = agentNames[0];
  $('stats-p1-name').textContent = agentNames[1];
  btnStart.disabled = true;
  btnStop.disabled = false;
  clearLog();
  setStatus('● RUNNING', 'running');
  addLog('Simulation started', 'info');
});

socket.on('hero_turn', data => {
  // Server prompts for user action.
  setMode('hero');
  updateHeroControlsFromPrompt(data);
  // Render state snapshot as the authoritative view
  renderGameState(data.state);
  addLog('Your turn', 'info');
});

socket.on('hero_action_ok', _data => {
  // Wait for the following game_state update.
  heroControls.style.display = 'none';
});

socket.on('hero_action_error', data => {
  setHeroControlsEnabled(true);
  showHeroError(data && data.message ? data.message : 'Invalid action');
});

socket.on('sim_stopped', data => {
  btnStart.disabled = false;
  btnStop.disabled = true;
  setStatus('● STOPPED', 'stopped');
  addLog('Simulation stopped', 'info');
});

socket.on('sim_stopping', data => {
  addLog('Stopping...', 'info');
});

socket.on('hand_start', data => {
  const state = data.state;
  renderGameState(state);
  agentNames = data.agent_names || agentNames;
  addLog(`━━ Hand #${state.hand_id} ━━ ${agentNames[0]} vs ${agentNames[1]}`, 'hand');
  // Clear per-hand bet displays
  $('p0-bet-display').textContent = '';
  $('p1-bet-display').textContent = '';
  $('p0-action-badge').textContent = '';
  $('p1-action-badge').textContent = '';
});

socket.on('game_state', data => {
  const state = data.state;
  const action = data.last_action;
  updateStats(data.stats);
  renderGameState(state);

  if (action) {
    const player = action.player;
    const type = action.type;
    const amount = action.amount;
    const name = agentNames[player] || `P${player}`;
    const cls = actionTypeClass(type);

    const badge = type.toUpperCase() + (amount > 0 ? ` ${fmt(amount)}` : '');
    showBadge(player, badge, cls);
    showBetDisplay(player, action.raise_size || amount || 0);

    const logText = `${name}: ${type.toUpperCase()}` + (amount > 0 ? ` ${fmt(amount)}` : '');
    addLog(logText, cls);

    updateAIDecision(action);
  }
});

socket.on('street_change', data => {
  const state = data.state;
  renderGameState(state);
  addLog(`── ${data.street} ──`, 'street');
  // Clear bet displays on new street
  $('p0-bet-display').textContent = '';
  $('p1-bet-display').textContent = '';
});

socket.on('hand_ended', data => {
  // Fold hand - render final state and log
  const state = data.state;
  renderGameState(state, true);
  updateStats(data.stats);

  const foldName = agentNames[data.fold_by] || `P${data.fold_by}`;
  const winnerName = agentNames[data.winner] || `P${data.winner}`;
  addLog(`${foldName} folds → ${winnerName} wins ${fmt(data.pot_won)}`, 'fold');
  showBadge(data.fold_by, 'FOLD', 'fold');
});

socket.on('paused', data => {
  // Showdown - render final state with all cards revealed
  const state = data.state;
  renderGameState(state, true);
  updateStats(data.stats);

  const winner = data.winner;
  const winnerName = winner === -1 ? 'Split' : (agentNames[winner] || `P${winner}`);
  addLog(`SHOWDOWN → ${winnerName} wins ${fmt(data.pot_won)}`, 'showdown');
  addLog(`Net: ${agentNames[0]} ${data.net_chips[0] >= 0 ? '+' : ''}${fmt(data.net_chips[0])}, ${agentNames[1]} ${data.net_chips[1] >= 0 ? '+' : ''}${fmt(data.net_chips[1])}`, 'winner');

  const msgWinner = winner === -1 ? 'Split Pot' : `${winnerName} Wins!`;
  const pauseEnabled = $('chk-pause').checked;

  if (pauseEnabled) {
    // Pause mode: show overlay then enter full pause
    showOverlay('Showdown', msgWinner, 1200);
    enterPauseMode(data);
  } else {
    // Auto-continue: overlay briefly, then resume immediately
    showOverlay('Showdown', msgWinner, 800);
    setTimeout(() => {
      socket.emit('resume');
      setStatus('● RUNNING', 'running');
    }, 850);
  }
});

socket.on('street_view', data => {
  // Revert navigation: show snapshot state
  const state = data.state;
  renderGameState(state, true);

  // Update log to show this street's actions
  const snap = data.snapshot;
  if (snap && snap.actions) {
    addLog(`--- Viewing ${data.street} ---`, 'street');
    snap.actions.forEach(a => {
      const name = agentNames[a.player] || `P${a.player}`;
      const cls = actionTypeClass(a.type);
      const amt = a.amount > 0 ? ` ${fmt(a.amount)}` : '';
      addLog(`  ${name}: ${a.type.toUpperCase()}${amt}`, cls);
    });
  }
});

socket.on('error', data => {
  addLog(`ERROR: ${data.message}`, 'fold');
  console.error('Server error:', data.message);
});

socket.on('resuming', data => {
  setStatus('● RUNNING', 'running');
});

// ---- Mode toggle ----
modeSelect.addEventListener('change', () => {
  setMode(modeSelect.value || 'sim');
});

// ---- Hero button handlers ----
btnHeroFold.addEventListener('click', () => sendHeroAction('fold'));
btnHeroCheck.addEventListener('click', () => sendHeroAction('check'));
btnHeroCall.addEventListener('click', () => sendHeroAction('call'));
btnHeroAllin.addEventListener('click', () => sendHeroAction('all_in'));
btnHeroBet.addEventListener('click', () => sendHeroAction('bet'));
btnHeroRaise.addEventListener('click', () => sendHeroAction('raise'));

// Init default mode
setMode(modeSelect.value || 'sim');
