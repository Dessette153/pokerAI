"""
main.py - CLI entry point for headless batch simulation and benchmarking

Usage:
  python main.py sim                          # 1000 el, simple rakip
  python main.py sim --hands 10000            # uzun simülasyon
  python main.py sim --hands 5000 --opponent random
  python main.py sim --hands 10000 --no-log   # log dosyası yazma
  python main.py bench                        # AI v1 vs random + simple karşılaştırma
  python main.py ui                           # Web UI'ı başlat
  python main.py test                         # engine/evaluator hızlı test
"""
import argparse
import sys
import time
from typing import List

import config as cfg


# ------------------------------------------------------------------ #
# Subcommand: sim
# ------------------------------------------------------------------ #

def cmd_sim(args):
    from app.engine.engine import GameEngine
    from app.agents.ai_v1 import AIv1
    from app.agents.simple_agent import SimpleAgent
    from app.agents.random_agent import RandomAgent
    from app.opponent_model.tracker import StatsTracker
    from app.logging.hand_logger import HandLogger
    from app.sim.simulator import SessionSimulator, simulate_hand

    # Batch sim için MC bütçesini düşür (UI'de 900ms, CLI'de 50ms yeterli)
    cfg.MC_TIME_BUDGET_MS = args.mc_budget
    cfg.MC_MIN_SAMPLES    = max(100, args.mc_budget * 2)
    cfg.MC_MAX_SAMPLES    = max(500, args.mc_budget * 20)

    engine = GameEngine(cfg.SB, cfg.BB)
    ai = AIv1('AI v1', seat=0)
    opp = RandomAgent('Random') if args.opponent == 'random' else SimpleAgent('Simple')
    agents = [ai, opp]

    tracker = StatsTracker()
    tracker.bb = cfg.BB

    sim = SessionSimulator(
        engine=engine,
        agents=agents,
        starting_stacks=[cfg.STARTING_STACK, cfg.STARTING_STACK],
        rebuy_to=cfg.STARTING_STACK,
    )

    logger = None
    if not args.no_log:
        import os; os.makedirs('logs', exist_ok=True)
        import datetime
        ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        log_path = f'logs/sim_{args.hands}hands_{ts}.jsonl'
        logger = HandLogger(log_path)
        logger.open()

    total = args.hands
    start = time.time()
    folds = 0
    showdowns = 0

    print(f"\n{'='*55}")
    print(f"  Poker AI - Batch Simulation")
    print(f"  {ai.name}  vs  {opp.name}")
    print(f"  {total} el  |  Stack: {cfg.STARTING_STACK:,}  |  Blinds: {cfg.SB}/{cfg.BB}")
    print(f"{'='*55}\n")

    report_every = max(1, total // 20)  # 5% aralıklarla durum raporu

    for hand_num in range(1, total + 1):
        gen = sim.next_hand_generator()
        result = None
        for event in gen:
            if event.type == 'hand_end':
                result = event.result
        sim.record_result(result)
        tracker.record_hand(result)
        if logger:
            logger.log_hand_result(result)

        if result.was_fold:
            folds += 1
        else:
            showdowns += 1

        if hand_num % report_every == 0 or hand_num == total:
            elapsed = time.time() - start
            hps = hand_num / elapsed
            stats = tracker.to_dict()
            p0 = stats['player0']
            pct = hand_num / total * 100
            net = p0['net_chips']
            net_str = f"+{net:,.0f}" if net >= 0 else f"{net:,.0f}"
            print(
                f"  {pct:5.1f}%  El:{hand_num:6d}  "
                f"bb/100:{stats['bb_per_100_p0']:+7.1f}  "
                f"Net:{net_str:>10}  "
                f"Win%:{p0['win_rate']:5.1f}%  "
                f"{hps:.0f} el/s"
            )

    elapsed = time.time() - start
    if logger:
        logger.close()

    stats = tracker.to_dict()
    p0 = stats['player0']
    p1 = stats['player1']

    print(f"\n{'='*55}")
    print(f"  SONUÇLAR  ({elapsed:.1f}s | {total/elapsed:.0f} el/s)")
    print(f"{'='*55}")
    print(f"\n  {ai.name}:")
    print(f"    bb/100  : {stats['bb_per_100_p0']:+.2f}")
    print(f"    Net     : {p0['net_chips']:+,.0f}")
    print(f"    Win%    : {p0['win_rate']:.1f}%")
    print(f"    VPIP    : {p0['vpip']}%")
    print(f"    PFR     : {p0['pfr']}%")
    print(f"    AF      : {p0['af']}")
    print(f"\n  {opp.name}:")
    print(f"    bb/100  : {stats['bb_per_100_p1']:+.2f}")
    print(f"    Net     : {p1['net_chips']:+,.0f}")
    print(f"    Win%    : {p1['win_rate']:.1f}%")
    print(f"\n  El istatistikleri:")
    print(f"    Fold    : {folds:,} ({folds/total*100:.1f}%)")
    print(f"    Showdown: {showdowns:,} ({showdowns/total*100:.1f}%)")
    if logger:
        print(f"\n  Log: {logger.log_path}")
    print()


# ------------------------------------------------------------------ #
# Subcommand: bench
# ------------------------------------------------------------------ #

def cmd_bench(args):
    """AI v1 vs Random + AI v1 vs Simple karşılaştırmalı benchmark."""
    from app.engine.engine import GameEngine
    from app.agents.ai_v1 import AIv1
    from app.agents.simple_agent import SimpleAgent
    from app.agents.random_agent import RandomAgent
    from app.opponent_model.tracker import StatsTracker
    from app.sim.simulator import SessionSimulator

    cfg.MC_TIME_BUDGET_MS = args.mc_budget
    cfg.MC_MIN_SAMPLES    = max(100, args.mc_budget * 2)
    cfg.MC_MAX_SAMPLES    = max(500, args.mc_budget * 20)

    hands = args.hands
    print(f"\n{'='*55}")
    print(f"  BENCHMARK  ({hands:,} el x 2 senaryo)")
    print(f"{'='*55}")

    results = {}
    for opp_name, OppClass in [('Random', RandomAgent), ('Simple', SimpleAgent)]:
        engine = GameEngine(cfg.SB, cfg.BB)
        ai = AIv1('AI v1', seat=0)
        opp = OppClass(opp_name)
        tracker = StatsTracker()
        tracker.bb = cfg.BB
        sim = SessionSimulator(engine, [ai, opp],
                               [cfg.STARTING_STACK]*2, rebuy_to=cfg.STARTING_STACK)
        start = time.time()
        for _ in range(hands):
            gen = sim.next_hand_generator()
            result = None
            for event in gen:
                if event.type == 'hand_end':
                    result = event.result
            sim.record_result(result)
            tracker.record_hand(result)
        elapsed = time.time() - start
        stats = tracker.to_dict()
        results[opp_name] = (stats, elapsed)
        print(f"\n  AI v1 vs {opp_name}:  ({elapsed:.1f}s)")
        p0 = stats['player0']
        print(f"    bb/100 = {stats['bb_per_100_p0']:+.2f}")
        print(f"    Win%   = {p0['win_rate']:.1f}%")
        print(f"    Net    = {p0['net_chips']:+,.0f}")

    print(f"\n{'='*55}\n")


# ------------------------------------------------------------------ #
# Subcommand: test
# ------------------------------------------------------------------ #

def cmd_test(args):
    """Engine ve evaluatör hızlı smoke test."""
    print("\n  Engine & Evaluator Test\n")
    errors = 0

    # 1. Evaluator
    from app.engine.cards import Card
    from app.engine.evaluator import evaluate_hand, hand_rank_name, compare_hands
    c = lambda s: Card.from_str(s)
    royal  = [c('Ah'), c('Kh'), c('Qh'), c('Jh'), c('Th'), c('2s'), c('3d')]
    pair   = [c('Ah'), c('As'), c('Kh'), c('Qd'), c('Jc'), c('2s'), c('3d')]
    high   = [c('Ah'), c('Ks'), c('Qh'), c('Jd'), c('9c'), c('2s'), c('3d')]
    assert 'Royal' in hand_rank_name(evaluate_hand(royal)), "Royal Flush başarısız"
    assert 'Pair' in hand_rank_name(evaluate_hand(pair)), "One Pair başarısız"
    assert compare_hands(evaluate_hand(royal), evaluate_hand(pair)) == 1, "Royal > Pair başarısız"
    print("  [OK] Evaluator")

    # 2. Engine - 10 tam el
    from app.engine.engine import GameEngine
    from app.agents.simple_agent import SimpleAgent
    from app.sim.simulator import simulate_hand
    engine = GameEngine(cfg.SB, cfg.BB)
    a0, a1 = SimpleAgent('P0', 0.0), SimpleAgent('P1', 0.0)
    ok = 0
    for i in range(10):
        gen = simulate_hand(engine, [a0, a1], i+1, [10000,10000], i%2)
        for ev in gen:
            if ev.type == 'hand_end':
                assert ev.result.final_state.is_terminal, "Terminal değil!"
                ok += 1
    assert ok == 10
    print("  [OK] Engine (10 el)")

    # 3. MC Equity
    from app.eval.equity import monte_carlo_equity
    from app.engine.cards import Card
    aa = [Card.from_str('Ah'), Card.from_str('As')]
    eq = monte_carlo_equity(aa, [], time_budget_ms=200, min_samples=500, max_samples=2000)
    assert 0.70 < eq < 0.90, f"AA equity beklentisi dışı: {eq:.3f}"
    print(f"  [OK] Monte Carlo equity (AA preflop = {eq:.1%})")

    # 4. AI v1 imports
    from app.agents.ai_v1 import AIv1, get_hand_tier
    assert get_hand_tier([Card.from_str('Ah'), Card.from_str('As')]) == 'S'
    assert get_hand_tier([Card.from_str('7h'), Card.from_str('2d')]) == 'D'
    print("  [OK] AI v1 tier chart")

    print("\n  Tüm testler geçti.\n")


# ------------------------------------------------------------------ #
# Subcommand: ui
# ------------------------------------------------------------------ #

def cmd_ui(args):
    from app.ui.server import socketio, app
    print(f"  Web UI başlatılıyor → http://{cfg.UI_HOST}:{cfg.UI_PORT}")
    print("  Durdurmak için Ctrl+C\n")
    socketio.run(app, host=cfg.UI_HOST, port=cfg.UI_PORT,
                 debug=False, allow_unsafe_werkzeug=True)


# ------------------------------------------------------------------ #
# Argument parser
# ------------------------------------------------------------------ #

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='python main.py',
        description='Poker AI - CLI',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Örnekler:
  python main.py ui
  python main.py sim --hands 10000
  python main.py sim --hands 5000 --opponent random --no-log
  python main.py bench --hands 10000
  python main.py test"""
    )
    sub = parser.add_subparsers(dest='command', help='Çalıştırılacak komut')

    # sim
    p_sim = sub.add_parser('sim', help='Batch headless simülasyon')
    p_sim.add_argument('--hands', type=int, default=1000, metavar='N',
                       help='Simüle edilecek el sayısı (default: 1000)')
    p_sim.add_argument('--opponent', choices=['simple', 'random'], default='simple',
                       help='Rakip ajan tipi (default: simple)')
    p_sim.add_argument('--no-log', action='store_true',
                       help='JSONL log dosyası yazma')
    p_sim.add_argument('--mc-budget', type=int, default=50, metavar='MS',
                       help='Monte Carlo zaman bütçesi ms (default: 50, UI: 900)')

    # bench
    p_bench = sub.add_parser('bench', help='AI v1 vs Random + Simple karşılaştırmalı benchmark')
    p_bench.add_argument('--hands', type=int, default=5000, metavar='N',
                         help='Her senaryo için el sayısı (default: 5000)')
    p_bench.add_argument('--mc-budget', type=int, default=50, metavar='MS',
                         help='Monte Carlo zaman bütçesi ms (default: 50)')

    # ui
    sub.add_parser('ui', help='Web UI başlat (http://localhost:5000)')

    # test
    sub.add_parser('test', help='Engine / evaluator smoke test')

    return parser


if __name__ == '__main__':
    parser = build_parser()
    args = parser.parse_args()

    if args.command == 'sim':
        cmd_sim(args)
    elif args.command == 'bench':
        cmd_bench(args)
    elif args.command == 'ui':
        cmd_ui(args)
    elif args.command == 'test':
        cmd_test(args)
    else:
        parser.print_help()
