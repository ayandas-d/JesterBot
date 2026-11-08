"""Summarize independent match blocks, retaining the judge's scoring units."""
import argparse
from collections import Counter, defaultdict
import json
from math import sqrt
from pathlib import Path
from statistics import mean, stdev

# Two-sided 95% Student t critical values; conservative df cap beyond table.
T = {1:12.706,2:4.303,3:3.182,4:2.776,5:2.571,6:2.447,7:2.365,8:2.306,9:2.262,
     10:2.228,11:2.201,12:2.179,13:2.160,14:2.145,15:2.131,16:2.120,17:2.110,
     18:2.101,19:2.093,20:2.086,30:2.042}

def interval(values):
    center = mean(values)
    if len(values) < 2:
        return [center, None, None]
    df = len(values)-1
    critical = T[max(k for k in T if k <= df)]
    margin = critical * stdev(values) / sqrt(len(values))
    return [center, center-margin, center+margin]

def summarize(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[(row['opponent'], row['variant'])].append(row)
    summary = []
    for (opponent, variant), group in groups.items():
        stats = [h for r in group for h in r['stats']['agent1']]
        opp_stats = [h for r in group for h in r['stats']['agent2']]
        diag = [d for r in group for d in r['diagnostics']]
        counts = Counter(r['verdict'] for r in group)
        summary.append(dict(opponent=opponent, variant=variant, matches=len(group),
            mean_and_match_cluster_ci=interval([r['mean'] for r in group]),
            wins=counts['AGENT1_WIN'], chops=counts['CHOP'], losses=counts['AGENT2_WIN'],
            max_time=max(h['time_seconds'] for h in stats),
            errors=sum(h['errors'] for h in stats),
            forfeits=sum(h['forfeited'] for h in stats),
            timeouts=sum(h['timed_out'] for h in stats),
            skipped_calls=sum(h['skipped_calls'] for h in stats),
            opponent_timeouts=sum(h['timed_out'] for h in opp_stats),
            safety_errors=sum(d['safety_errors'] for d in diag),
            timing_open=sum(d['gate']=='open' for d in diag),
            timing_nudges=sum(d['nudges'] for d in diag),
            lowered_k=sum(d['lowered_k'] for d in diag)))
    differences=[]
    for opponent in sorted({r['opponent'] for r in rows}):
        original={r['seed']:r for r in groups[(opponent,'original')]}
        for variant in ('no_timing','aggro_start'):
            delta=[r['mean']-original[r['seed']]['mean'] for r in groups[(opponent,variant)] if r['seed'] in original]
            if delta:
                differences.append(dict(opponent=opponent, variant=variant, matches=len(delta),
                    delta_vs_original_and_match_cluster_ci=interval(delta)))
    return dict(groups=summary, paired_differences=differences)

if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('summary', type=Path)
    args=p.parse_args()
    result=summarize(json.loads(args.summary.read_text()))
    (args.summary.parent/'analysis.json').write_text(json.dumps(result,indent=2)+'\n')
    for r in result['groups']:
        print(r['opponent'],r['variant'],r['matches'],[round(v,3) if v is not None else None for v in r['mean_and_match_cluster_ci']],f"W/D/L {r['wins']}/{r['chops']}/{r['losses']}",f"time {r['max_time']:.2f}", f"nudges {r['timing_nudges']}")
    print('Paired differences:',json.dumps(result['paired_differences'],indent=2))
