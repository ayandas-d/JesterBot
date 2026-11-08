"""Keep measuring/evolving local adversaries without modifying Jester or champions.

Foreground: BOT_SEED=7 .venv/bin/python -B tools/continuous.py --jobs 2
macOS background (from the repository):
  nohup env BOT_SEED=7 .venv/bin/python -B tools/continuous.py --jobs 2 > /tmp/jester-continuous.log 2>&1 &
Stop: touch league/STOP. In-flight matches finish; no new stage starts. Remove
STOP and restart to resume. SIGTERM follows the same graceful-stop path.
Seed reservations survive restarts; abandoned in-flight seeds are replaced.
Only this runner's old raw artifacts rotate. Hall-of-fame bots never rotate.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
from datetime import datetime,timezone
import json
import fcntl
import os
from pathlib import Path
import re
import signal
import shutil
import subprocess
import sys
import tempfile
from threading import Event
from time import monotonic

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools import league
from tools.evolve_adversary import evolve
from tools.league_alerts import alert,open_alerts,DEFAULT as ALERTS
from tools.league_state import reserve_seeds

STATE=ROOT/"league/continuous_state.json"
STOP=ROOT/"league/STOP"
DASHBOARD=ROOT/"league/DASHBOARD.md"


def latest_champion():
    tags=subprocess.check_output(["git","tag","--list","champion-v*"],cwd=ROOT,text=True).splitlines()
    versions=[tag.removeprefix("champion-") for tag in tags if re.fullmatch(r"champion-v[1-9]\d*",tag)]
    if not versions:raise ValueError("No tagged champion")
    version=max(versions,key=lambda name:int(name[1:]))
    path=league.resolve_snapshot(version)
    commit=json.loads((path/"META.json").read_text())["commit_sha"]
    tagged=subprocess.check_output(["git","rev-parse",f"champion-{version}^{{commit}}"],cwd=ROOT,text=True).strip()
    if commit!=tagged:raise ValueError("Champion tag and immutable manifest disagree")
    return version,commit


def save_state(state):
    temporary=STATE.with_suffix(".new");temporary.write_text(json.dumps(state,indent=2)+"\n");temporary.replace(STATE)


def recover_inflight(active,completed=()):
    for item in active.get("running",[]):
        if (item["opponent"],str(item["seed"])) in completed:
            continue
        old=item["seed"];replacement=reserve_seeds(1,"abandoned-match-replacement")[0]
        for key in ("plan","training_plan","oracle_plan"):
            for planned in active.get(key,[]):
                if planned["opponent"]==item["opponent"] and planned["seed"]==old:
                    planned["seed"]=replacement
        active.setdefault("abandoned_seeds",[]).append(old)
    active["running"]=[]
    active["metadata"]["seeds"]=[str(item["seed"]) for item in active["plan"]]


def rotating_slice(config,cycle,size):
    names=config["training"]["opponents"]+league.champions()
    groups={tier:[name for name in names if league.tier_of(name,config)==tier] for tier in ("F","H")}
    result=[]
    for i in range(size):
        tier=("F","H")[i%2]
        choices=groups[tier]
        if not choices:continue
        candidate=choices[((cycle-1)*max(1,size//2)+i//2)%len(choices)]
        if candidate not in result:result.append(candidate)
    return result


def alert_row(row,context):
    issues=row.get("safety_violations",[])
    if issues:alert(context+"/safety","SAFETY",f"{context}: {issues}")
    if row.get("tier","F")!="C" and row.get("verdict")=="AGENT2_WIN":
        alert(context+"/loss","FAIR LOSS",f"{context}: {row['bb_per_deal']:+.4f} bb/deal, CI {row['ci']}")


def dashboard(state,status):
    recent=state.get("cycles",[])
    active=state.get("active") or {}
    lines=["# Jester league dashboard","",f"Updated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
           f"Status: {status}. Champion: {state.get('champion','pending')} / {state.get('champion_commit','pending')}.",
           f"Completed cycles: {state.get('completed_cycles',0)}; active phase: {active.get('phase','none')}.","",
           "## Safety record","",f"Safe completed-match hands: {state.get('safe_hands',0):,}; "
           f"current safe-hand streak: {state.get('safe_streak',0):,}; incidents: {state.get('incidents',0)}.",
           "Counts are conservative whole-match units; an unsafe match contributes no safe hands.","",
           "## Recent tier samples","","These rotating slices use fresh seeds and changing opponents; they are not full-field promotion scores.","",
           "| Cycle | Tier | Matches | Points | bb/deal |","| --- | --- | ---: | ---: | ---: |"]
    for cycle in recent[-10:]:
        for tier,stats in cycle["tiers"].items():
            if stats["matches"]:
                points="—" if stats["points"] is None else str(stats["points"])
                lines.append(f"| {cycle['cycle']} | {tier} | {stats['matches']} | {points} | {stats['mean_bb_per_deal']:+.4f} |")
    hardest=sorted([item for cycle in recent[-20:] for item in cycle.get("matchups",[]) if item["tier"]!="C"],
                   key=lambda item:item["bb_per_deal"])[:10]
    lines += ["","## Hardest recent fair matchups","","| Opponent | Tier | bb/deal | Seed |","| --- | --- | ---: | ---: |"]
    for row in hardest:lines.append(f"| {row['opponent']} | {row['tier']} | {row['bb_per_deal']:+.4f} | {row['seed']} |")
    lines += ["","## Cheater-loss trend","","Cheater results never enter fair points.",""]
    for cycle in recent[-10:]:
        for row in cycle.get("matchups",[]):
            if row["tier"]=="C":lines.append(f"- Cycle {cycle['cycle']}, {row['opponent']}: Jester {row['bb_per_deal']:+.4f} bb/deal.")
    lines += ["","## Open alerts","",*open_alerts(ALERTS)[-30:]]
    if not open_alerts(ALERTS):lines.append("No open alerts.")
    temporary=DASHBOARD.with_suffix(".new");temporary.write_text("\n".join(lines)+"\n");temporary.replace(DASHBOARD)


def run_rows(state,active,args,stop_signal):
    path=ROOT/active["result"]
    document=json.loads(path.read_text()) if path.exists() else dict(metadata=active["metadata"],complete=False,matches=[])
    document.update(metadata=active["metadata"],complete=False)
    completed={(r["opponent"],str(r["seed"])) for r in document["matches"]}
    pending=[item for item in active["plan"] if (item["opponent"],str(item["seed"])) not in completed]
    executor=ThreadPoolExecutor(max_workers=args.jobs);futures={};cursor=0
    stop=Event()
    def persist():
        document["summary"]=league.summarize(document["matches"])
        path.write_text(json.dumps(document,indent=2)+"\n")
        save_state(state)
    try:
        while cursor<len(pending) or futures:
            stopping=STOP.exists() or stop_signal.is_set()
            while not stopping and cursor<len(pending) and len(futures)<args.jobs:
                item=pending[cursor];cursor+=1
                context=f"cycle{active['cycle']}/{item['opponent']}/seed{item['seed']}"
                directory=Path(active["logs"])/(item["opponent"]+"-"+str(item["seed"]))
                active.setdefault("running",[]).append(item)
                save_state(state)
                future=executor.submit(league.run_one,active["champion"],item["opponent"],str(item["seed"]),
                    args.deals,directory,active["config"],stop,True,600,args.bot_seed,True,"configured",False,False,args.jobs,
                    {"path":ALERTS,"context":context})
                futures[future]=(item,context)
            if not futures:break
            done,_=wait(futures,timeout=.2,return_when=FIRST_COMPLETED)
            for future in done:
                item,context=futures.pop(future)
                try:row=future.result()
                except Exception as exc:
                    row=dict(opponent=item["opponent"],seed=str(item["seed"]),
                             safety_violations=[f"infrastructure: {exc}"])
                active["running"].remove(item)
                document["matches"].append(row)
                alert_row(row,context)
                if row["safety_violations"]:
                    state["incidents"]+=1;state["safe_streak"]=0
                elif "raw" in row:
                    state["safe_hands"]+=2*args.deals;state["safe_streak"]+=2*args.deals
                persist();dashboard(state,"measuring")
        document["complete"]=len(document["matches"])==len(active["plan"])
        persist()
        return document["complete"],document
    except BaseException:
        stop.set()
        raise
    finally:
        executor.shutdown(wait=True,cancel_futures=True)


def run_sweep(active,args,seed):
    output=Path(active["logs"])/"safety.json"
    command=[sys.executable,"-B",str(ROOT/"tools/safety_sweep.py"),"--champion",active["champion"],
             "--hands",str(args.fuzz_hands),"--seed",str(seed),"--json",str(output)]
    process=subprocess.Popen(command,cwd=ROOT,start_new_session=True)
    try:code=process.wait()
    finally:
        if process.poll() is None:
            os.killpg(process.pid,signal.SIGTERM);process.wait(timeout=20)
        try:os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:pass
    if code or not output.exists():raise RuntimeError("Frozen champion safety sweep failed")
    return json.loads(output.read_text())


def rotate_raw(state,maximum_bytes=64*1024*1024,keep_cycles=20):
    # Only artifacts explicitly owned by completed continuous cycles rotate.
    # Active results, unrelated audit evidence and all source/HOF files remain.
    artifacts=state.get("raw_artifacts",[])
    def size(item):
        path=Path(item)
        return sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) if path.is_dir() else path.stat().st_size if path.exists() else 0
    while len(artifacts)>max(2,keep_cycles) or sum(size(item) for item in artifacts)>maximum_bytes:
        if len(artifacts)<=2:break
        item=Path(artifacts.pop(0)).resolve()
        if item.is_relative_to((ROOT/"league/results").resolve()) and ("continuous-cycle-" in item.name or "evolution" in item.name):
            item.unlink(missing_ok=True)
            item.with_suffix(item.suffix+".gz").unlink(missing_ok=True)
        elif item.is_relative_to(Path("/tmp").resolve()) and item.name.startswith(("jester-continuous-","adversary-search-","league-evolution-")):
            shutil.rmtree(item,ignore_errors=True)
        else:
            raise ValueError("Refusing to rotate an unowned artifact")
    state["raw_artifacts"]=artifacts


def run(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs",type=int,default=2)
    parser.add_argument("--cycles",type=int,help="optional finite operational verification")
    parser.add_argument("--slice-size",type=int,default=6)
    parser.add_argument("--seeds-per-opponent",type=int,default=3)
    parser.add_argument("--deals",type=int,default=1000)
    parser.add_argument("--fuzz-hands",type=int,default=2000)
    parser.add_argument("--oracle-every",type=int,default=5)
    parser.add_argument("--evolution-population",type=int,default=6)
    parser.add_argument("--max-raw-mb",type=int,default=64)
    args=parser.parse_args(argv)
    args.bot_seed=os.environ.get("BOT_SEED","7")
    if min(args.jobs,args.slice_size,args.seeds_per_opponent,args.oracle_every)<1 or args.deals<1000 or args.fuzz_hands<1000:
        parser.error("Use positive limits and at least1,000 deals/fuzz hands")
    args.jobs=min(args.jobs,max(1,(os.cpu_count() or 1)//2))
    stop_signal=Event()
    def request_stop(*_):
        stop_signal.set();STOP.touch()
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,request_stop)
    state=json.loads(STATE.read_text()) if STATE.exists() else dict(completed_cycles=0,cycles=[],safe_hands=0,
        safe_streak=0,incidents=0,raw_artifacts=[],active=None)
    if not ALERTS.exists():ALERTS.write_text("# League alerts\n\nUnchecked entries remain open. No incidents recorded yet.\n")
    completed_this_run=0
    while not STOP.exists() and not stop_signal.is_set() and (args.cycles is None or completed_this_run<args.cycles):
        if not state.get("active"):
            champion,commit=latest_champion();state.update(champion=champion,champion_commit=commit)
            config=league.load_config();cycle=state["completed_cycles"]+1
            opponents=rotating_slice(config,cycle,args.slice_size)
            seeds=iter(reserve_seeds(len(opponents)*args.seeds_per_opponent,f"cycle{cycle}/training"))
            stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            active=dict(cycle=cycle,champion=champion,phase="training",config=config,
                plan=[dict(opponent=name,seed=next(seeds)) for name in opponents for _ in range(args.seeds_per_opponent)],
                result=f"league/results/{stamp}_continuous-cycle-{cycle}.json",
                logs=tempfile.mkdtemp(prefix=f"jester-continuous-{cycle}-",dir="/tmp"),running=[],
                immutable=league.runtime_hashes(league.resolve_snapshot(champion)),
                live_immutable=league.runtime_hashes(ROOT),
                metadata=dict(label=f"continuous-cycle-{cycle}",timestamp=stamp,challenger=champion,commit=commit,
                              group="training",deals=args.deals,seeds=[],jobs=args.jobs,bot_seed=args.bot_seed))
            active["metadata"]["seeds"]=[str(item["seed"]) for item in active["plan"]]
            state["active"]=active;save_state(state)
        active=state["active"]
        # Only crashed in-flight matches need new seeds. Never replay a seed
        # that may already have reached a judge before the supervisor stopped.
        if active.get("running"):
            result=ROOT/active["result"]
            saved=json.loads(result.read_text())["matches"] if result.exists() else []
            recover_inflight(active,{(r["opponent"],str(r["seed"])) for r in saved});save_state(state)
        dashboard(state,"running")
        try:
            if active["phase"]=="training":
                complete,document=run_rows(state,active,args,stop_signal)
                if not complete:break
                active["phase"]="evolution";save_state(state)
            if STOP.exists() or stop_signal.is_set():break
            if active["phase"]=="evolution":
                block=reserve_seeds(600,f"cycle{active['cycle']}/evolution")
                active["evolution"]=evolve(active["champion"],population=args.evolution_population,
                    generations=1,jobs=args.jobs,seed_base=block[0],keep=1,stop_file=STOP)
                for name in active["evolution"]["published"]:
                    config=league.load_config();meta=json.loads((ROOT/config["opponents"][name]["script"]).with_name("META.json").read_text())
                    result=meta["confirmation"]
                    if result["ci"][1]<0:alert(name,"NEW ADVERSARY",f"{name} beats {active['champion']}: Jester {result['mean_bb_per_deal']:+.4f}, CI {result['ci']}")
                active["phase"]="safety";save_state(state)
            if STOP.exists() or stop_signal.is_set():break
            if active["phase"]=="safety":
                active["sweep"]=run_sweep(active,args,reserve_seeds(1,"safety-fuzz")[0])
                active["phase"]="oracle";save_state(state)
            if STOP.exists() or stop_signal.is_set():break
            if active["phase"]=="oracle" and active["cycle"]%args.oracle_every==0:
                if not active.get("oracle_plan"):
                    original=active["plan"];active["training_plan"]=original
                    config=league.load_config();names=[n for n in config["opponents"] if league.tier_of(n,config)=="C"]
                    seeds=reserve_seeds(len(names),f"cycle{active['cycle']}/oracle")
                    active["oracle_plan"]=[dict(opponent=n,seed=s) for n,s in zip(names,seeds)]
                active["plan"]=active["training_plan"]+active["oracle_plan"]
                complete,document=run_rows(state,active,args,stop_signal)
                if not complete:break
            if league.runtime_hashes(league.resolve_snapshot(active["champion"]))!=active["immutable"] or league.runtime_hashes(ROOT)!=active["live_immutable"]:
                raise RuntimeError("Live or champion runtime changed during continuous measurement")
            document=json.loads((ROOT/active["result"]).read_text());summary=league.summarize(document["matches"])
            cycle_record=dict(cycle=active["cycle"],tiers=summary["tiers"],result=active["result"],
                matchups=[{key:r.get(key) for key in ("opponent","seed","tier","bb_per_deal")} for r in document["matches"] if "raw" in r],
                adversaries=active.get("evolution",{}).get("published",[]),sweep=active["sweep"])
            state["cycles"]=(state.get("cycles",[])+[cycle_record])[-200:]
            state["completed_cycles"]=active["cycle"]
            league.append_history(ROOT/"league/history.csv",dict(timestamp=active["metadata"]["timestamp"],label=f"continuous-cycle-{active['cycle']}",
                challenger=active["champion"],commit=state["champion_commit"],group="rotating-training-plus-separate-C",
                deals=args.deals,seeds=";".join(str(i["seed"]) for i in active["plan"]),matches=summary["completed_matches"],
                points=summary["tournament_points"],mean_bb_per_deal=summary["mean_bb_per_deal"],worst_matchup=summary["worst_matchup"],
                safety_violations=len(summary["safety_violations"]),complete=True,result=active["result"]))
            state["raw_artifacts"] += [str(ROOT/active["result"]),active["logs"],
                *active.get("evolution",{}).get("owned_results",[]),
                *active.get("evolution",{}).get("owned_log_directories",[])]
            state["active"]=None;completed_this_run+=1
            rotate_raw(state,args.max_raw_mb*1024*1024);save_state(state);dashboard(state,"cycle completed")
        except InterruptedError:
            save_state(state);break
        except Exception as exc:
            alert(f"cycle{active['cycle']}/supervisor","SAFETY",str(exc));state["incidents"]+=1
            save_state(state);dashboard(state,"stopped on failure");raise
    save_state(state);dashboard(state,"stopped cleanly")
    print(json.dumps(dict(completed_this_run=completed_this_run,completed_total=state["completed_cycles"],
                          stopped_by_file=STOP.exists(),pending_phase=(state.get("active") or {}).get("phase"))))


def main(argv=None):
    STATE.parent.mkdir(parents=True,exist_ok=True)
    with STATE.with_suffix(".lock").open("a+") as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise SystemExit("A continuous runner already owns this state")
        return run(argv)


if __name__=="__main__":main()
