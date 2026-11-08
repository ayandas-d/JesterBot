"""Locked monotone seed reservations: restarts and concurrent tools cannot reuse them."""

from collections import deque
import csv
from datetime import datetime,timezone
import fcntl
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def reserve_seeds(count,purpose,path=None,minimum=1000,reserved=()):
    if count<1:raise ValueError("Seed count must be positive")
    path=Path(path) if path else ROOT/"league/seed_state.json"
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.with_suffix(".lock").open("a+") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if path.exists():
            state=json.loads(path.read_text())
        else:
            used=[]
            history=ROOT/"league/history.csv" if path.parent==ROOT/"league" else None
            if history and history.exists():
                with history.open() as stream:
                    used=[int(seed) for row in csv.DictReader(stream) for seed in row["seeds"].split(";") if seed.isdigit()]
            state=dict(next_seed=max([minimum,*[s+1 for s in used]]),recent=[])
        cursor=max(minimum,state["next_seed"])
        excluded=set(reserved);seeds=[]
        while len(seeds)<count:
            if cursor not in excluded:seeds.append(cursor)
            cursor+=1
        recent=deque(state.get("recent",[]),maxlen=128)
        recent.append(dict(purpose=purpose,first=seeds[0],last=seeds[-1],count=count,
                           reserved_at=datetime.now(timezone.utc).isoformat()))
        state.update(next_seed=cursor,recent=list(recent))
        temporary=path.with_suffix(".new");temporary.write_text(json.dumps(state,indent=2)+"\n");temporary.replace(path)
        return seeds
