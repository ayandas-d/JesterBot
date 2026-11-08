"""Explicit minimal privileges attached only to the oracle HTTP handle."""

import json
import os
from pathlib import Path

KINDS = ("oracle_full", "oracle_partial", "board_oracle", "unlimited_compute", "oracle_counter")


def notify_safety(handle):
    """External observer only; called after the copied judge has charged time."""
    if not getattr(handle, "oracle_is_target", False) or not os.environ.get("LEAGUE_ALERT_PATH"):
        return
    stats=handle.stats
    if stats.errors or stats.forfeited or stats.timed_out or stats.time_seconds>4:
        from tools.league_alerts import alert
        context=os.environ.get("LEAGUE_ALERT_CONTEXT","oracle match")
        half=getattr(handle,"oracle_half",0)
        alert(f"{context}/half{half}/safety","SAFETY",
              f"{context}/half{half}: errors={stats.errors}, forfeit={stats.forfeited}, "
              f"timeout={stats.timed_out}, charged={stats.time_seconds:.6f}s",
              Path(os.environ["LEAGUE_ALERT_PATH"]))


def information(game, seat, kind, state_path):
    if kind not in KINDS:
        raise ValueError(f"Unknown oracle kind: {kind}")
    result = {"kind": kind}
    if kind in ("oracle_full", "oracle_partial"):
        count = 5 if kind == "oracle_full" else 2
        result["opponent_hole"] = list(game.deal.hole_cards[1-seat][:count])
    elif kind == "board_oracle":
        visible = len(game.observation(seat).board)
        result["next_board_card"] = game.deal.board[visible] if visible < 5 else None
    elif kind == "oracle_counter":
        state = None
        if state_path:
            try:
                candidate = json.loads(Path(state_path).read_text())
                # This is the latest actual harness state. Batched results
                # mean its last observed hand can precede the current deal.
                # The observer resets the channel at every new_half.
                if isinstance(candidate,dict) and -1 <= int(candidate.get("hand_index",-2)) <= game.hand_index:
                    state = candidate
            except (OSError, ValueError, TypeError):
                pass
        result["target_state"] = state
    return result
