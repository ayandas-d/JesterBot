"""Append immediate, deduplicated markdown alerts under a cross-process file lock."""

from datetime import datetime,timezone
import fcntl
import hashlib
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DEFAULT=ROOT/"league/ALERTS.md"


def alert(key,kind,message,path=DEFAULT):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    marker="<!-- id:"+hashlib.sha256(key.encode()).hexdigest()[:20]+" -->"
    message=" ".join(str(message).splitlines())
    with path.open("a+") as stream:
        fcntl.flock(stream,fcntl.LOCK_EX)
        stream.seek(0);previous=stream.read()
        if marker in previous:return False
        if not previous:stream.write("# League alerts\n\nUnchecked entries remain open. Checked entries are resolved; keep their history.\n\n")
        stream.seek(0,2)
        stamp=datetime.now(timezone.utc).isoformat(timespec="seconds")
        stream.write(f"- [ ] **{kind}** {stamp}: {message} {marker}\n")
        stream.flush()
    return True


def open_alerts(path=DEFAULT):
    path=Path(path)
    return [line for line in path.read_text().splitlines() if line.startswith("- [ ]")] if path.exists() else []
