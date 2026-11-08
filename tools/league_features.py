"""Pure tier, cache and planned-look helpers for the local league runner."""

import hashlib
import json
from math import sqrt
import re
from statistics import mean, stdev, NormalDist


def tier_of(name, config):
    if re.fullmatch(r"v[1-9]\d*", name):
        return "H"
    return config.get("opponents", {}).get(name, {}).get("tier", "F")


def distribution(values):
    if not values:
        return dict(deals=0, mean_bb_per_deal=None, ci=None)
    average = mean(values)
    width = 1.96*stdev(values)/sqrt(len(values)) if len(values) > 1 else 0
    return dict(deals=len(values), mean_bb_per_deal=average, ci=[average-width, average+width])


def tier_summary(rows):
    complete = [r for r in rows if "raw" in r]
    tiers = {}
    for tier in ("F", "H", "C"):
        selected = [r for r in complete if r.get("tier", "F") == tier]
        tiers[tier] = dict(distribution([v for r in selected for v in r["raw"]["paired_bb"]]),
                           matches=len(selected),
                           points=sum(r["points"] for r in selected) if tier != "C" else None)
    fair = [r for r in complete if r.get("tier", "F") != "C"]
    return dict(tiers=tiers, fair_points=sum(r["points"] for r in fair),
                fair_mean_bb_per_deal=distribution([v for r in fair for v in r["raw"]["paired_bb"]])["mean_bb_per_deal"])


def cache_key(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def decisive(values, seeds, minimum_seeds=20, maximum_looks=20, margin=.05):
    """Bonferroni planned-look normal intervals, not repeated unadjusted 95% CIs.

    Normal approximation still assumes independent duplicate-deal returns;
    this is a screening aid, not an unconditional confidence sequence.
    Full promotion continues to require at least twenty independent seeds.
    """
    if seeds < minimum_seeds or len(values) < 2:
        return None
    critical = NormalDist().inv_cdf(1-.05/(2*max(1, maximum_looks)))
    width = critical*stdev(values)/sqrt(len(values))
    average = mean(values)
    if average-width > margin:
        return "positive"
    if average+width < -margin:
        return "negative"
    return None
