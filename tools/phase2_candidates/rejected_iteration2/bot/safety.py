"""Exception containment for the three participant entry points.

Diagnostics go only to stderr. Even a broken stderr stream must not turn a
recoverable policy failure into an HTTP error and tournament forfeit.
"""

from functools import wraps
import sys
import traceback

from game import Action


def _report_failure(name, memory):
    try:
        memory["safety_errors"] = memory.get("safety_errors", 0) + 1
    except Exception:
        pass
    try:
        print(f"[bot safety] {name} failed; using safe fallback", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
    except Exception:
        pass


def safe_action(function):
    @wraps(function)
    def wrapped(obs, memory):
        try:
            action = function(obs, memory)
            # IntEnum equality would otherwise allow True or raw integer 1.
            if not isinstance(action, Action) or action not in obs.legal_actions:
                raise ValueError(f"illegal policy action: {action!r}")
            return action
        except Exception:
            _report_failure(function.__name__, memory)
            return Action.CHECK_CALL
    return wrapped


def safe_callback(function):
    @wraps(function)
    def wrapped(value, memory):
        try:
            function(value, memory)
        except Exception:
            _report_failure(function.__name__, memory)
        return None
    return wrapped
