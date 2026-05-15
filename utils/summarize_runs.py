"""Summarize testing/runs.jsonl by config and category.

Usage:
    python -m utils.summarize_runs                              # table all configs
    python -m utils.summarize_runs --configs A,B                # filter
    python -m utils.summarize_runs --diff base=A,cmp=B          # per-level ratios
    python -m utils.summarize_runs --runs-file path/to.jsonl    # alt input
"""

import argparse
import json
import os
import statistics
import sys
from collections import defaultdict
from typing import Dict, List, Tuple

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_runs(runs_file: str) -> List[Dict]:
    rows = []
    if not os.path.exists(runs_file):
        return rows
    with open(runs_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return rows


def quantile(values: List[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    pos = q * (len(s) - 1)
    lo, hi = int(pos), min(int(pos) + 1, len(s) - 1)
    frac = pos - lo
    return s[lo] * (1 - frac) + s[hi] * frac


def print_table(rows: List[Dict], configs: List[str]) -> None:
    # Group rows by (config, category)
    by_cc: Dict[Tuple[str, str], List[Dict]] = defaultdict(list)
    cats = set()
    for r in rows:
        if configs and r.get("config") not in configs:
            continue
        cfg = r.get("config", "?")
        cat = r.get("category", "?")
        by_cc[(cfg, cat)].append(r)
        cats.add(cat)

    cat_order = [c for c in ("small", "medium", "large") if c in cats]
    cfg_order = configs if configs else sorted({k[0] for k in by_cc})

    print(f"\n{'Config':45s}  {'Cat':6s}  {'Solved':>10s}  "
          f"{'Timeout':>7s}  {'Err':>4s}  {'Median':>8s}  {'p90':>8s}  {'Max':>8s}")
    print("-" * 110)
    for cfg in cfg_order:
        any_data = False
        for cat in cat_order:
            rs = by_cc.get((cfg, cat), [])
            if not rs:
                continue
            any_data = True
            total = len(rs)
            solved_rs = [r for r in rs if r.get("solved")]
            solved = len(solved_rs)
            timeout = sum(1 for r in rs if r.get("timed_out"))
            err = sum(1 for r in rs if r.get("error") and not r.get("timed_out"))
            times = [r["elapsed_s"] for r in solved_rs if r.get("elapsed_s") is not None]
            med = statistics.median(times) if times else 0.0
            p90 = quantile(times, 0.90)
            mx  = max(times) if times else 0.0
            print(f"{cfg:45s}  {cat:6s}  "
                  f"{solved:>3d}/{total:<3d}     "
                  f"{timeout:>7d}  {err:>4d}  "
                  f"{med:>7.2f}s {p90:>7.2f}s {mx:>7.2f}s")
        if any_data:
            print()


def print_diff(rows: List[Dict], base: str, cmp_: str) -> None:
    by_cfg_level: Dict[Tuple[str, str], Dict] = {}
    for r in rows:
        by_cfg_level[(r.get("config"), r.get("level_path"))] = r

    base_levels = {lp: r for (cfg, lp), r in by_cfg_level.items() if cfg == base}
    cmp_levels  = {lp: r for (cfg, lp), r in by_cfg_level.items() if cfg == cmp_}
    shared = sorted(set(base_levels) & set(cmp_levels))
    if not shared:
        print(f"No shared levels between {base!r} and {cmp_!r}")
        return

    deltas: List[Tuple[float, str, str, float, float, str]] = []
    for lp in shared:
        b = base_levels[lp]
        c = cmp_levels[lp]
        bs, cs = b.get("solved"), c.get("solved")
        bt, ct = b.get("elapsed_s"), c.get("elapsed_s")
        if not bs or not cs:
            tag = f"{'B' if bs else '-'}{'C' if cs else '-'}"
            deltas.append((float("inf"), lp, b.get("category", "?"), bt or 0, ct or 0, tag))
            continue
        ratio = (ct or 0) / max(bt or 1e-9, 1e-9)
        deltas.append((ratio, lp, b.get("category", "?"), bt, ct, "ok"))

    valid = [d for d in deltas if d[5] == "ok"]
    if not valid:
        print("No levels solved in both configs.")
        return

    valid.sort(key=lambda x: x[0])
    print(f"\nDiff: {base}  vs  {cmp_}  (ratio = cmp / base; <1 = cmp faster)")
    print(f"  {len(valid)} levels solved in both;  geomean ratio = "
          f"{statistics.geometric_mean([d[0] for d in valid]):.3f}")
    print(f"  median ratio = {statistics.median([d[0] for d in valid]):.3f}")

    print("\nTop 10 cmp speedups (smallest ratio):")
    print(f"  {'ratio':>7s}  {'cat':6s}  {'base s':>8s}  {'cmp s':>8s}  level")
    for d in valid[:10]:
        print(f"  {d[0]:7.3f}  {d[2]:6s}  {d[3]:>7.3f}s {d[4]:>7.3f}s  {d[1]}")

    print("\nBottom 10 cmp regressions (largest ratio):")
    for d in valid[-10:][::-1]:
        print(f"  {d[0]:7.3f}  {d[2]:6s}  {d[3]:>7.3f}s {d[4]:>7.3f}s  {d[1]}")

    # Coverage diff
    base_solved = {lp for lp, r in base_levels.items() if r.get("solved")}
    cmp_solved  = {lp for lp, r in cmp_levels.items()  if r.get("solved")}
    only_base = base_solved - cmp_solved
    only_cmp  = cmp_solved - base_solved
    print(f"\nCoverage:  base-only solved = {len(only_base)},  "
          f"cmp-only solved = {len(only_cmp)}")
    for lp in sorted(only_base)[:5]:
        print(f"  base-only: {lp}")
    for lp in sorted(only_cmp)[:5]:
        print(f"  cmp-only:  {lp}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--runs-file", default=os.path.join(_REPO_ROOT, "testing/runs.jsonl"))
    p.add_argument("--configs", action="append", default=[],
                   help="Filter to a config key (repeatable). Config keys contain commas, "
                        "so we don't split on comma — pass --configs once per key.")
    p.add_argument("--diff", default=None,
                   help="base=CFG_A,cmp=CFG_B  — print per-level ratio table.")
    args = p.parse_args()

    rows = load_runs(args.runs_file)
    if not rows:
        print(f"No rows in {args.runs_file}")
        return

    if args.diff:
        parts = dict(kv.split("=", 1) for kv in args.diff.split(","))
        print_diff(rows, parts["base"], parts["cmp"])
        return

    print_table(rows, args.configs)


if __name__ == "__main__":
    main()
