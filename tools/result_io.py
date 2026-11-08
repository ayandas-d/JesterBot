"""Lossless gzip archives for old raw JSON; readers accept either representation.

python tools/result_io.py --older-than 120 --exclude ACTIVE_RESULT.json
Only league/results JSON is archived by this CLI. No source or hall-of-fame
file is touched. The uncompressed bytes are verified before removing a copy.
"""

import argparse
import gzip
import json
from pathlib import Path
import time

ROOT=Path(__file__).resolve().parents[1]


def read_result(path):
    path=Path(path)
    if path.suffix==".gz":return json.loads(gzip.decompress(path.read_bytes()))
    if path.exists():return json.loads(path.read_text())
    return json.loads(gzip.decompress(path.with_suffix(path.suffix+".gz").read_bytes()))


def archive_result(path):
    path=Path(path);before=path.stat();data=path.read_bytes()
    target=path.with_suffix(path.suffix+".gz")
    if target.exists():
        if gzip.decompress(target.read_bytes())!=data:raise ValueError("Conflicting archive; original retained")
    else:
        compressed=gzip.compress(data,compresslevel=3,mtime=0)
        if gzip.decompress(compressed)!=data:raise ValueError("Archive verification failed")
        temporary=target.with_suffix(target.suffix+".tmp")
        temporary.write_bytes(compressed);temporary.replace(target)
    after=path.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
        raise ValueError("Result changed during archival; original retained")
    path.unlink()
    return target


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--older-than",type=float,default=120)
    parser.add_argument("--exclude",nargs="*",default=[])
    args=parser.parse_args();cutoff=time.time()-args.older_than
    count=before=after=0
    for path in (ROOT/"league/results").rglob("*.json"):
        if path.name in args.exclude or path.stat().st_mtime>cutoff:continue
        size=path.stat().st_size;archived=archive_result(path)
        count+=1;before+=size;after+=archived.stat().st_size
    print(json.dumps(dict(files=count,uncompressed_bytes=before,archived_bytes=after)))


if __name__=="__main__":main()
