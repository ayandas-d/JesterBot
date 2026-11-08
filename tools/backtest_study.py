"""Sequential official-judge study, fresh processes per half, persisted raw data.

Variants only change the experiment adapter. No engine or submission edits.
"""
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from time import monotonic
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.run_matches import ROOT, OPPONENTS, processes, health, read_diagnostics
from judge_engine import HalfResult, combine_halves

def run(opponent, seed, variant, directory, deals):
    directory.mkdir(parents=True, exist_ok=True)
    halves, diagnostics = [], []
    for half in (1, 2):
        with ExitStack() as stack, processes() as owned:
            sockets = [stack.enter_context(socket.socket()) for _ in range(2)]
            for sock in sockets:
                sock.bind(('127.0.0.1', 0))
            ports = [sock.getsockname()[1] for sock in sockets]
            for i, script in enumerate(('tools/backtest_server.py', OPPONENTS[opponent])):
                sockets[i].close()
                log = stack.enter_context((directory / f'h{half}-agent{i+1}.log').open('w'))
                env = dict(os.environ, PORT=str(ports[i]), AGENT_TOKEN='',
                           BOT_SEED=f'strategy-{seed}-{half}', BACKTEST_VARIANT=variant)
                p = subprocess.Popen([sys.executable, script], cwd=ROOT, env=env,
                                     stdout=log, stderr=subprocess.STDOUT)
                owned.append(p)
                health(p, ports[i], monotonic() + 15)
            log = stack.enter_context((directory / f'h{half}-judge.log').open('w'))
            out = directory / f'half{half}.json'
            p = subprocess.Popen([sys.executable, 'judge_engine.py', '--half', str(half),
                '--agent1', str(ports[0]), '--agent2', str(ports[1]), '--deals', str(deals),
                '--seed', str(seed), '--json', str(out.resolve())], cwd=ROOT,
                env=dict(os.environ, AGENT1_TOKEN='', AGENT2_TOKEN=''), stdout=log, stderr=subprocess.STDOUT)
            owned.append(p)
            if p.wait(timeout=240):
                raise RuntimeError(f'judge failed: {directory}')
        halves.append(HalfResult.from_dict(json.loads(out.read_text())))
        diagnostics.extend(d for d in read_diagnostics(directory / f'h{half}-agent1.log') if d['final'])
    result = combine_halves(*halves).to_dict()
    (directory / 'match.json').write_text(json.dumps(result, indent=2) + '\n')
    row = dict(opponent=opponent, seed=seed, variant=variant,
               mean=result['mean_bb_per_deal'], ci=result['ci'], verdict=result['verdict'],
               stats=result['agent_stats'], diagnostics=diagnostics,
               directory=str(directory.resolve().relative_to(ROOT)))
    return row

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seeds', nargs='+', default=['101','102','103','104','105'])
    parser.add_argument('--variants', nargs='+', choices=['original','no_timing','aggro_start'], default=['original'])
    parser.add_argument('--opponents', nargs='+', choices=list(OPPONENTS), default=list(OPPONENTS))
    parser.add_argument('--deals', type=int, default=1000)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    summary = args.output / 'summary.json'
    rows = json.loads(summary.read_text()) if summary.exists() else []
    finished = {(r['opponent'],r['seed'],r['variant']) for r in rows}
    # Interleave variants; never run matches concurrently (timing contamination).
    for opponent in args.opponents:
        for seed in args.seeds:
            for variant in args.variants:
                if (opponent,seed,variant) in finished:
                    continue
                row = run(opponent, seed, variant, args.output / f'{opponent}-{seed}-{variant}', args.deals)
                rows.append(row)
                summary.write_text(json.dumps(rows, indent=2) + '\n')
                print(f'{len(rows)} {opponent} {seed} {variant}: {row["mean"]:+.3f} {row["ci"]} {row["verdict"]}', flush=True)

if __name__ == '__main__':
    main()
