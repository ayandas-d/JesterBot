"""Training-only random search followed by a small standard-library genetic search.

python tools/evolve_adversary.py --champion v2 --population 6 --generations 1 --jobs 1 --reserve-holdout
Quick screens use 300 duplicate deals; confirmation uses 1,000. Seed blocks
must be fresh between rounds (continuous.py allocates them). No holdout score
is read. Published adversaries are immutable and are never removed.
"""

import argparse
import csv
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
from random import Random
import shutil
import signal
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.build_league import refresh_hashes
from tools.result_io import read_result

DOMAINS = dict(preflop_floor=(.0,.66), call_floor=(0.,.62), call_margin=(-.05,.15),
               raise_threshold=(.45,.90), raise_frequency=(.55,1.), bluff=(0.,.22),
               pot_fraction=(0.,1.), reraise_threshold=(.52,.90), range_bias=(0.,1.))
IDEAS = ("balanced", "folder_lock", "value_trap", "reraise_bait", "detector_bait", "range_reader", "gear_cycle")


def random_parameters(rng):
    result = {key: round(rng.uniform(*bounds),5) for key,bounds in DOMAINS.items()}
    result.update(idea=rng.choice(IDEAS), seed=rng.randrange(1000000), samples=80,
                  preflop_samples=24, bait_length=rng.randint(8,120), switch_every=rng.randint(25,150))
    return result


def child_parameters(a,b,rng):
    result = deepcopy(rng.choice((a,b)))
    for key,(lo,hi) in DOMAINS.items():
        value = rng.choice((a[key],b[key]))
        if rng.random() < .40:
            value += rng.gauss(0,(hi-lo)*.12)
        result[key] = round(max(lo,min(hi,value)),5)
    if rng.random() < .15:
        result["idea"] = rng.choice(IDEAS)
    result.update(seed=rng.randrange(1000000),
                  bait_length=max(8,min(120,int(rng.choice((a["bait_length"],b["bait_length"]))+rng.gauss(0,10)))))
    return result


def write_frozen(path, parameters, details):
    path = Path(path)
    path.mkdir(parents=True,exist_ok=False)
    for source,target in (("parametric.py","family.py"),("server.py","server.py")):
        shutil.copyfile(ROOT/"league/opponents"/source,path/target)
    text = f'''"""Frozen evolved fair adversary. PORT selects its server; META.json records provenance."""
import importlib.util
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p/"game.py").is_file())
sys.path.insert(0,str(ROOT))

def load(name):
    spec = importlib.util.spec_from_file_location("frozen_"+HERE.name+"_"+name,HERE/(name+".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module

family, server = load("family"), load("server")
PARAMETERS = {parameters!r}

def new_half(config,memory):
    family.initialize(config,memory,PARAMETERS)

def choose_action(obs,memory):
    return family.choose(obs,memory,PARAMETERS)

def on_hand_end(result,memory):
    pass

app = server.create_app(HERE.name,new_half,choose_action,on_hand_end)

if __name__ == "__main__":
    server.serve(app)
'''
    (path/"agent.py").write_text(text)
    metadata = dict(details,parameters=deepcopy(parameters),created_at=datetime.now(timezone.utc).isoformat(),
                    source_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in path.glob("*.py")})
    (path/"META.json").write_text(json.dumps(metadata,indent=2)+"\n")
    return metadata


def verify_frozen(path):
    path=Path(path);metadata=json.loads((path/"META.json").read_text())
    expected=metadata["source_sha256"]
    if set(expected)!={p.name for p in path.glob("*.py")}:
        raise ValueError("Changed immutable adversary file set")
    for name,digest in expected.items():
        if Path(name).name!=name or hashlib.sha256((path/name).read_bytes()).hexdigest()!=digest:
            raise ValueError("Changed immutable adversary source")
    return metadata


def qualified(document):
    summary=document["summary"]
    return (document["complete"] and not summary["safety_violations"]
            and summary["mean_bb_per_deal"] is not None and summary["mean_bb_per_deal"] < .5)


def evaluate(champion, cases, seeds, deals, jobs, label, directory, stop_file=None):
    if stop_file and Path(stop_file).exists():raise InterruptedError("Evolution stopped before launching a stage")
    config=json.loads((ROOT/"league/config.json").read_text())
    for name,path in cases.items():
        config["opponents"][name]=dict(script=str(path.relative_to(ROOT)),tier="H")
    config_path=directory/(label+"-config.json")
    config_path.write_text(json.dumps(config))
    command=[sys.executable,"-B",str(ROOT/"tools/league.py"),"--config",str(config_path),
             "--challenger",champion,"--opponents",*cases,"--seeds",*map(str,seeds),
             "--deals",str(deals),"--jobs",str(jobs),"--label",label]
    previous=set((ROOT/"league/results").glob(f"*_{label}.json"))
    process=subprocess.Popen(command,cwd=ROOT,start_new_session=True)
    try:
        while True:
            try:
                code=process.wait(timeout=.25)
                break
            except subprocess.TimeoutExpired:
                if stop_file and Path(stop_file).exists():raise InterruptedError("Evolution stopped")
    finally:
        try: os.killpg(process.pid,signal.SIGTERM)
        except ProcessLookupError: pass
        if process.poll() is None:
            try: process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid,signal.SIGKILL);process.wait()
        try:os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:pass
    created=set((ROOT/"league/results").glob(f"*_{label}.json"))-previous
    if len(created)!=1:
        raise RuntimeError("Evolution evaluation did not save exactly one record")
    path=created.pop();document=json.loads(path.read_text())
    if code or not document["complete"] or document["summary"]["safety_violations"]:
        raise RuntimeError(f"Evolution safety/infrastructure failure; inspect {path}")
    return path,document


def publish(parameters, champion, evidence, reserve_holdout=False):
    lock_path=ROOT/"league/.config.lock"
    with lock_path.open("a+") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        config_path=ROOT/"league/config.json";config=json.loads(config_path.read_text())
        parent=ROOT/"league/opponents/evolved";parent.mkdir(exist_ok=True)
        number=1
        while (parent/f"e{number:04}").exists():number+=1
        name=f"evolved_e{number:04}"
        destination=parent/f"e{number:04}"
        target_commit=json.loads((ROOT/f"league/champions/{champion}/META.json").read_text())["commit_sha"]
        write_frozen(destination,parameters,dict(target_champion=champion,target_commit=target_commit,
                     confirmation=evidence,reserved_holdout=reserve_holdout))
        config["opponents"][name]=dict(script=str((destination/"agent.py").relative_to(ROOT)),tier="H",evolved=True)
        group=config["holdout"] if reserve_holdout else config["training"]
        group["opponents"].append(name)
        if reserve_holdout:group.pop("evolved_reserve_pending",None)
        config.setdefault("hall_of_fame",[]).append(name)
        refresh_hashes(config)
        temporary=config_path.with_suffix(".new");temporary.write_text(json.dumps(config,indent=2)+"\n");temporary.replace(config_path)
        return name


def evolve(champion="v2", population=6, generations=1, jobs=1, seed_base=50000, reserve_holdout=False, keep=2, stop_file=None):
    if population<4 or generations<1:
        raise ValueError("Use at least four random candidates and one genetic generation")
    rng=Random(seed_base)
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    scratch=ROOT/"league/opponents/_search"/stamp;scratch.mkdir(parents=True)
    logs=Path(tempfile.mkdtemp(prefix="adversary-search-",dir="/tmp"))
    all_parameters={};ranked=[]
    def screen(parameters,generation):
        cases={}
        for i,p in enumerate(parameters):
            name=f"search_{stamp}_{generation}_{i}"
            path=scratch/name
            write_frozen(path,p,dict(target_champion=champion,screening=True))
            cases[name]=path/"agent.py";all_parameters[name]=p
        path,report=evaluate(champion,cases,[seed_base+generation*10+1,seed_base+generation*10+2],300,jobs,
                             f"evolution-{stamp}-g{generation}",logs,stop_file)
        return [(stats["mean_bb_per_deal"],name,str(path)) for name,stats in report["summary"]["opponents"].items()]
    ranked=screen([random_parameters(rng) for _ in range(population)],0)
    for generation in range(1,generations+1):
        parents=[all_parameters[name] for _,name,_ in sorted(ranked)[:max(2,population//2)]]
        children=[child_parameters(rng.choice(parents),rng.choice(parents),rng) for _ in range(population)]
        ranked+=screen(children,generation)
    final_names=[name for _,name,_ in sorted(ranked)[:keep+int(reserve_holdout)]]
    cases={name:scratch/name/"agent.py" for name in final_names}
    confirmation_path,confirmation=evaluate(champion,cases,[seed_base+501,seed_base+502,seed_base+503],1000,jobs,
                                             f"evolution-{stamp}-confirm",logs,stop_file)
    saved=[]
    for index,name in enumerate(final_names):
        row=confirmation["summary"]["opponents"][name]
        if row["mean_bb_per_deal"] >= .5:
            continue
        evidence=dict(path=str(confirmation_path.relative_to(ROOT)),**row)
        is_reserve=reserve_holdout and index==len(final_names)-1
        saved.append(publish(all_parameters[name],champion,evidence,is_reserve))
    report=dict(champion=champion,seed_base=seed_base,population=population,generations=generations,
                screening=sorted(ranked),parameters=all_parameters,
                confirmation=str(confirmation_path.relative_to(ROOT)),published=saved)
    output=ROOT/"league/results"/f"{stamp}_evolution.json"
    report["result_file"]=str(output.relative_to(ROOT))
    evaluated={Path(row[2]) for row in ranked}|{confirmation_path}
    report["owned_results"]=[str(p) for p in sorted(evaluated)]+[str(output)]
    report["owned_log_directories"]=[str(logs)]+[read_result(p)["metadata"]["log_directory"] for p in sorted(evaluated)]
    output.write_text(json.dumps(report,indent=2)+"\n")
    history=ROOT/"league/evolution_history.csv"
    with history.open("a+",newline="") as stream:
        fcntl.flock(stream,fcntl.LOCK_EX);stream.seek(0,2)
        writer=csv.writer(stream,lineterminator="\n")
        if stream.tell()==0:writer.writerow(("date","champion","seed_base","candidate","screen_champion_bb","parameters","confirmation","published"))
        for score,name,_ in sorted(ranked):
            writer.writerow((stamp,champion,seed_base,name,score,json.dumps(all_parameters[name],sort_keys=True),
                             str(confirmation_path.relative_to(ROOT)),";".join(saved)))
        stream.flush()
    # Only transient search candidates are removed; every published hall-of-
    # fame directory is elsewhere and is permanently retained.
    shutil.rmtree(scratch)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--champion",default="v2")
    parser.add_argument("--population",type=int,default=6)
    parser.add_argument("--generations",type=int,default=1)
    parser.add_argument("--jobs",type=int,default=1)
    parser.add_argument("--seed-base",type=int,default=50000)
    parser.add_argument("--reserve-holdout",action="store_true")
    parser.add_argument("--keep",type=int,default=2)
    parser.add_argument("--stop-file",type=Path)
    args=parser.parse_args()
    print(json.dumps(evolve(**vars(args)),indent=2))


if __name__=="__main__":main()
