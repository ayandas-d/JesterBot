"""Offline runtime audit and doubled-sample slow-machine proxy.

Run: BOT_SEED=7 .venv/bin/python -B tools/harden_submission.py
Writes its report only to /tmp. Hooks prohibit outbound sockets, subprocesses
and writes elsewhere while importing and exercising the actual bot.
"""

import json
import os
from pathlib import Path
from random import Random
import resource
import subprocess
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True  # mirrors the tournament base image
TRACKED = set(subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines())
AUDIT = {"writes": [], "blocked": []}


def audit(event, args):
    if event in ("socket.connect", "socket.getaddrinfo", "socket.sendto", "socket.sendmsg",
                 "subprocess.Popen", "os.system"):
        AUDIT["blocked"].append(event)
        raise RuntimeError(f"runtime attempted forbidden external operation: {event}")
    if event in ("os.remove", "os.rename", "os.mkdir", "os.rmdir", "os.chmod", "os.symlink", "os.link"):
        for path in args[:2 if event in ("os.rename", "os.symlink", "os.link") else 1]:
            if isinstance(path, (str, bytes, os.PathLike)):
                resolved = Path(os.fsdecode(path)).resolve()
                if not resolved.is_relative_to(Path("/tmp").resolve()):
                    AUDIT["blocked"].append(f"{event}: {resolved}")
                    raise RuntimeError(f"runtime attempted mutation outside /tmp: {event}: {resolved}")
                AUDIT["writes"].append(f"{event}: {resolved}")
    if event == "open":
        path, mode, flags = args
        writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
            isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)))
        if writing and isinstance(path, (str, bytes, os.PathLike)):
            resolved = Path(os.fsdecode(path)).resolve()
            if not resolved.is_relative_to(Path("/tmp").resolve()):
                AUDIT["blocked"].append(str(resolved))
                raise RuntimeError(f"runtime attempted write outside /tmp: {resolved}")
            AUDIT["writes"].append(str(resolved))


sys.addaudithook(audit)
import agent
from bot import equity
from game import Action, AgentConfig, Game, make_deal


def benchmark(opponent):
    memory = {}
    agent.new_half(AgentConfig(), memory)
    # Do not let budget reductions conceal the cost of doubled sample counts.
    memory["bot"].governor.budget_seconds = 1_000_000
    rng = Random(0)
    elapsed = 0.0
    decisions = 0
    peak_decision = 0.0
    for index in range(1000):
        game = Game(make_deal("hardening-7", index), index % 2, hand_index=index)
        while not game.is_terminal:
            obs = game.observation(game.to_act)
            if game.to_act == 0:
                start = perf_counter()
                action = agent.choose_action(obs, memory)
                duration = perf_counter() - start
                elapsed += duration
                peak_decision = max(peak_decision, duration)
                decisions += 1
            elif opponent == "random":
                action = rng.choice(obs.legal_actions)
            elif opponent == "calling_station":
                action = Action.CHECK_CALL
            else:
                action = Action.RAISE_POT if Action.RAISE_POT in obs.legal_actions else Action.CHECK_CALL
            game.apply(action)
        start = perf_counter()
        agent.on_hand_end(game.hand_result(0), memory)
        elapsed += perf_counter() - start
    report = {"opponent": opponent, "hands": 1000, "decisions": decisions,
              "seconds": elapsed, "max_decision_ms": peak_decision * 1000,
              "errors": memory["safety_errors"], "governor_reductions": memory["bot"].governor.reductions}
    assert report["errors"] == report["governor_reductions"] == 0, report
    assert elapsed < 8, report
    print(json.dumps(report), flush=True)
    return report


def main():
    original_samples = dict(equity.SAMPLES)
    equity.SAMPLES.update({street: count * 2 for street, count in original_samples.items()})
    benchmarks = [benchmark(opponent) for opponent in ("random", "calling_station", "pot_maniac")]
    runtime_files = set()
    for name, module in tuple(sys.modules.items()):
        filename = getattr(module, "__file__", None)
        if name == "__main__" or not filename:
            continue
        path = Path(filename).resolve()
        if path == Path(__file__).resolve():
            continue  # multiprocessing may alias the audit driver as __mp_main__
        if path.is_relative_to(ROOT):
            relative = path.relative_to(ROOT)
            if relative.parts[0] != ".venv":
                runtime_files.add(str(relative))
    missing = runtime_files - TRACKED
    assert not missing, f"Uncommitted runtime imports: {missing}"
    assert not AUDIT["blocked"], AUDIT
    assert not AUDIT["writes"], AUDIT  # no runtime file writes, even to /tmp
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_bytes = rss if sys.platform == "darwin" else rss * 1024
    assert peak_bytes < 512 * 1024 * 1024, peak_bytes
    runtime_bytes = sum((ROOT / path).stat().st_size for path in runtime_files)
    report = {"doubled_samples": equity.SAMPLES, "benchmarks": benchmarks,
              "peak_rss_bytes": peak_bytes, "peak_rss_mib": peak_bytes / 1024**2,
              "runtime_imports": sorted(runtime_files), "all_runtime_imports_tracked": True,
              "runtime_source_bytes": runtime_bytes, "runtime_file_writes": list(AUDIT["writes"]),
              "blocked_operations": list(AUDIT["blocked"]), "bytecode_writes_disabled": sys.dont_write_bytecode,
              "runtime_requirements": (ROOT / "requirements.txt").read_text().splitlines()}
    output = Path("/tmp/heads-up-task7-hardening.json")
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Peak RSS: {peak_bytes / 1024**2:.1f} MiB; tracked runtime imports: {len(runtime_files)}; report: {output}")


if __name__ == "__main__":
    main()
