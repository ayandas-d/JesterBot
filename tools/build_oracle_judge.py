"""Reproduce the separate oracle judge from the immutable tournament source.

Writes only tools/oracle_judge/engine.py. Tests pin the real source digest.
Deals, actions, legality, scores, HTTP charging and duplicate scoring are kept.
The only privileges belong to the agent2 handle, including after seats swap.
"""

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL_SHA256 = "fa7a7e3fb49c09588cfcf0930a8e3f6c189e419dbc54263ae7d53b953223d422"

ORACLE_HANDLE = '''
_original_oracle_post = HttpAgentHandle._post
def _oracle_observed_post(self, label, path, body):
    if label == "new_half":
        self.oracle_half = getattr(self, "oracle_half", 0) + 1
    try:
        return _original_oracle_post(self, label, path, body)
    finally:
        from tools.oracle_judge.privileges import notify_safety
        notify_safety(self)
HttpAgentHandle._post = _oracle_observed_post

class OracleAgentHandle(HttpAgentHandle):
    """Agent2 only: explicit unfair information; compute oracle has a huge bank."""
    def __init__(self, base_url, config, token=None, *, kind):
        if kind == "unlimited_compute":
            from dataclasses import replace
            config = replace(config, time_bank_seconds=1e9)
        super().__init__(base_url, config, token)
        self.kind, self.extra = kind, {}

    def _post(self, label, path, body):
        if path == "/act":
            body = dict(body, oracle=self.extra)
        return super()._post(label, path, body)

'''


def build():
    source = (ROOT / "judge_engine.py").read_bytes()
    if hashlib.sha256(source).hexdigest() != ORIGINAL_SHA256:
        raise ValueError("The protected real judge differs from the original")
    text = source.decode()
    substitutions = [
        ("import argparse\n", "import argparse\nfrom pathlib import Path\nimport sys\nsys.path.insert(0, str(Path(__file__).resolve().parents[2]))\nfrom tools.oracle_judge.privileges import information, KINDS\n"),
        ("@dataclass\nclass HalfResult:", ORACLE_HANDLE + "@dataclass\nclass HalfResult:"),
        ("            game.apply(bots[seat].act(game.observation(seat)))",
         "            if isinstance(bots[seat], OracleAgentHandle):\n"
         "                bots[seat].extra = information(game, seat, bots[seat].kind, os.environ.get('ORACLE_STATE_PATH'))\n"
         "            game.apply(bots[seat].act(game.observation(seat)))"),
        ("    args = build_parser().parse_args(argv)  # exits with code 2 on bad options",
         "    parser = build_parser()\n    parser.add_argument('--oracle-kind', choices=KINDS, required=True)\n    args = parser.parse_args(argv)"),
        ('        bot2 = HttpAgentHandle(bot_url(args.agent2), config, os.environ.get("AGENT2_TOKEN"))',
         '        bot2 = OracleAgentHandle(bot_url(args.agent2), config, os.environ.get("AGENT2_TOKEN"), kind=args.oracle_kind)'),
        ('        bot1 = HttpAgentHandle(bot_url(args.agent1), config, os.environ.get("AGENT1_TOKEN"))',
         '        bot1 = HttpAgentHandle(bot_url(args.agent1), config, os.environ.get("AGENT1_TOKEN"))\n        bot1.oracle_is_target = True'),
    ]
    for old, new in substitutions:
        if text.count(old) != 1:
            raise ValueError(f"Unexpected original-judge structure: {old[:80]}")
        text = text.replace(old, new, 1)
    target = ROOT / "tools/oracle_judge/engine.py"
    target.write_text(text)
    return target


if __name__ == "__main__":
    print(build())
