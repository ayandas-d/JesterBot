"""Test-only prefix telemetry around the real judge's unchanged public APIs.

No requests, actions, deals, scoring or charged-clock calculations are changed.
Only normal hand_end boundaries copy already accumulated AgentStats. The bot
never imports this module or receives these external measurements.
"""

import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import judge_engine as judge
from game import AgentConfig
from tools.league_alerts import alert


class ObservedHandle(judge.HttpAgentHandle):
    def __init__(self, *args, role=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.prefixes = []
        self.role, self.half_number = role, 0

    def _post(self, *args, **kwargs):
        try:
            return super()._post(*args, **kwargs)
        finally:
            if self.role == "agent1" and os.environ.get("LEAGUE_ALERT_PATH"):
                stats = self.stats
                if stats.errors or stats.forfeited or stats.timed_out or stats.time_seconds > 4:
                    context = os.environ.get("LEAGUE_ALERT_CONTEXT", "observed match")
                    message = (f"{context}/half{self.half_number}: errors={stats.errors}, "
                               f"forfeit={stats.forfeited}, timeout={stats.timed_out}, charged={stats.time_seconds:.6f}s")
                    try:
                        alert(f"{context}/half{self.half_number}/safety", "SAFETY", message,
                              Path(os.environ["LEAGUE_ALERT_PATH"]))
                    except OSError as exc:
                        print(f"ALERT_WRITER_ERROR {exc}", file=sys.stderr, flush=True)

    def start_half(self):
        self.half_number += 1
        super().start_half()
        self.prefixes.append({})

    def hand_end(self, result):
        super().hand_end(result)
        hands = result.hand_index + 1
        if hands in (300, 500, 700, 900):
            self.prefixes[-1][str(hands)] = self.stats.to_dict()

    def flush_hand_results(self):
        super().flush_hand_results()
        self.prefixes[-1][str(self.config.num_hands)] = self.stats.to_dict()


def main():
    args = judge.build_parser().parse_args()
    if args.half or args.deals < 1:
        raise SystemExit("Timing audit requires a duplicate match with positive deal count")
    config = AgentConfig(num_hands=args.deals)
    handles = [ObservedHandle(judge.bot_url(address), config, os.environ.get(token), role=role)
               for role,address,token in (("agent1",args.agent1,"AGENT1_TOKEN"),("agent2",args.agent2,"AGENT2_TOKEN"))]
    try:
        if not all(h.wait_healthy(judge.STARTUP_TIMEOUT_SECONDS) for h in handles):
            raise RuntimeError("audit server did not become healthy")
        judge.warmup()
        result = judge.play_match(*handles, args.seed, args.deals, keep_logs=args.logs)
        report = result.to_dict()
        report["timing_reference"] = {
            "scope": "normal hand-end boundary; final entry includes final callback delivery",
            "clock": "unchanged judge charged HTTP clock, per-request 1 ms grace",
            "agent1": handles[0].prefixes, "agent2": handles[1].prefixes}
        if args.json:
            Path(args.json).write_text(json.dumps(report, indent=2) + "\n")
        print(judge.format_report(result), flush=True)
    finally:
        for handle in handles:
            handle._close()


if __name__ == "__main__":
    main()
