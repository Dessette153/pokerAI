# Poker AI - Configuration Parameters
# PDF spec defaults

# Blinds & Stack
SB = 50
BB = 100
STARTING_STACK = 10_000

# Decision timing
DECISION_TIME_LIMIT_MS = 1000

# Monte Carlo equity
MC_TIME_BUDGET_MS = 900
MC_MIN_SAMPLES = 2000
MC_MAX_SAMPLES = 20000

# AI v1 strategy
MARGIN = 0.03          # equity margin for call/fold decisions
OPEN_SIZE_BB = 2.5     # default open raise in BBs
THREBET_IP_MULT = 3.0  # 3-bet multiplier in position
THREBET_OOP_MULT = 4.0 # 3-bet multiplier out of position
BLUFF_RATE = 0.12

# Preflop tier B randomization
TIER_B_RAISE_PROB = 0.60
TIER_B_CALL_PROB = 0.40

# Postflop bet sizing (fraction of pot)
BET_LARGE = 0.75   # value bet
BET_MEDIUM = 0.50  # thin value
BET_SMALL = 0.33   # semi-bluff

# Simulation
FOLD_PAUSE_MS = 800   # ms to pause after fold before next hand

# UI
UI_HOST = "127.0.0.1"
UI_PORT = 5000

# Agent names
SEAT_NAMES = {0: "AI v1", 1: "Opponent"}
