"""Analysis of benchmark runs from testing/runs.jsonl.

Produces a printed report and saves plots to testing/plots/.

Usage:
    venv/bin/python testing/analysis.py [--runs-file testing/runs.jsonl] [--plots]
"""

import argparse
import json
import os
from collections import Counter, defaultdict
from statistics import mean, median, stdev

# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def load_records(runs_file: str):
    with open(runs_file) as f:
        return [json.loads(l) for l in f if l.strip()]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def heuristic_cells(record) -> int:
    return sum(
        s["cells_forced"]
        for cyc in record["cycles"]
        for s in cyc["heuristic_steps"]
    )


def solver_cells(record) -> int:
    return sum(
        s["cells_forced"]
        for cyc in record["cycles"]
        for s in cyc["solver_steps"]
    )


def solver_iterations(record) -> int:
    return sum(len(cyc["solver_steps"]) for cyc in record["cycles"])


def fmt(n, width=6):
    return str(round(n, 3)).rjust(width)


# ---------------------------------------------------------------------------
# Report sections
# ---------------------------------------------------------------------------

def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def report_overview(recs):
    section("Dataset Overview")
    configs = sorted(set(r["config"] for r in recs))
    cats = Counter(r["category"] for r in recs)
    errors = [r for r in recs if r["error"] and not r["timed_out"]]
    err_types = Counter(r["error"].split(":")[0] for r in errors)

    print(f"  Total records    : {len(recs)}")
    print(f"  Unique configs   : {len(configs)}")
    print(f"  Levels per config: {len(recs) // len(configs)}")
    print(f"  By category      : small={cats['small']}  medium={cats['medium']}  large={cats['large']}")
    print(f"  Parse errors     : {len(errors)} ({', '.join(f'{v}×{k[:30]}' for k,v in err_types.most_common())})")
    print(f"\n  Configs:")
    for c in configs:
        print(f"    {c}")


def report_solve_rates(recs):
    section("Solve Rates by Config and Category")
    configs = sorted(set(r["config"] for r in recs))
    categories = ["small", "medium", "large"]

    header = f"  {'Config':<35}" + "".join(f"  {c:>8}" for c in categories) + "  {'Total':>8}"
    print(header)
    print("  " + "-" * (len(header) - 2))

    for cfg in configs:
        cfg_recs = [r for r in recs if r["config"] == cfg]
        parts = []
        total_solved = total_n = 0
        for cat in categories:
            sub = [r for r in cfg_recs if r["category"] == cat]
            solved = sum(1 for r in sub if r["solved"])
            n = sum(1 for r in sub if not r["error"])
            total_solved += solved
            total_n += n
            parts.append(f"{solved}/{n}".rjust(8) if n else "     n/a")
        total_str = f"{total_solved}/{total_n}".rjust(8)
        print(f"  {cfg:<35}" + "  ".join(f"  {p}" for p in parts) + f"  {total_str}")


def report_timing(recs):
    section("Solve Time by Config (solved levels only, seconds)")
    configs = sorted(set(r["config"] for r in recs))

    header = f"  {'Config':<35}  {'n':>5}  {'median':>8}  {'mean':>8}  {'stdev':>8}  {'max':>8}"
    print(header)
    print("  " + "-" * (len(header) - 2))

    for cfg in configs:
        times = [r["elapsed_s"] for r in recs if r["config"] == cfg and r["solved"]]
        if not times:
            continue
        print(
            f"  {cfg:<35}  {len(times):>5}  "
            f"{fmt(median(times)):>8}  {fmt(mean(times)):>8}  "
            f"{fmt(stdev(times) if len(times)>1 else 0):>8}  {fmt(max(times)):>8}"
        )


def report_heuristic_contribution(recs):
    section("Heuristic Contribution (configs with heuristics only)")
    h_configs = [c for c in sorted(set(r["config"] for r in recs)) if "h=none" not in c]
    if not h_configs:
        print("  No heuristic configs found.")
        return

    for cfg in h_configs:
        solved = [r for r in recs if r["config"] == cfg and r["solved"]]
        if not solved:
            continue
        print(f"\n  Config: {cfg}  (n={len(solved)} solved)")

        total_h = sum(heuristic_cells(r) for r in solved)
        total_s = sum(solver_cells(r) for r in solved)
        total = total_h + total_s
        print(f"    Cells forced by heuristics : {total_h:>6}  ({100*total_h/total:.1f}%)")
        print(f"    Cells forced by solver     : {total_s:>6}  ({100*total_s/total:.1f}%)")

        fracs = [heuristic_cells(r) / r["total"] for r in solved]
        pure_h = sum(1 for r in solved if solver_cells(r) == 0)
        print(f"    Levels solved by heuristics alone: {pure_h}/{len(solved)}")
        print(f"    Heuristic cell% per level: "
              f"min={min(fracs)*100:.1f}%  "
              f"median={median(fracs)*100:.1f}%  "
              f"mean={mean(fracs)*100:.1f}%  "
              f"max={max(fracs)*100:.1f}%")


def report_speedup(recs):
    section("Speedup: Heuristics+Solver vs Solver-Only")
    baseline_cfg = "h=none;s=gurobi;M=100"
    h_configs = [
        c for c in sorted(set(r["config"] for r in recs))
        if "h=none" not in c and "gurobi" in c
    ]
    if not h_configs or not any(r["config"] == baseline_cfg for r in recs):
        print("  Need both a heuristic config and h=none;s=gurobi;M=100 for comparison.")
        return

    baseline = {r["level_path"]: r for r in recs if r["config"] == baseline_cfg and r["solved"]}

    for cfg in h_configs:
        h_recs = [r for r in recs if r["config"] == cfg and r["solved"]]
        speedups = []
        for r in h_recs:
            b = baseline.get(r["level_path"])
            if b and b["elapsed_s"] and r["elapsed_s"]:
                speedups.append(b["elapsed_s"] / r["elapsed_s"])
        if not speedups:
            continue
        speedups.sort()
        improved = sum(1 for s in speedups if s > 1.05)
        slowed = sum(1 for s in speedups if s < 0.95)
        print(f"\n  {cfg} vs {baseline_cfg}")
        print(f"    n={len(speedups)} paired levels")
        print(f"    Speedup: min={min(speedups):.2f}x  median={median(speedups):.2f}x  "
              f"mean={mean(speedups):.2f}x  max={max(speedups):.2f}x")
        print(f"    Faster with heuristics : {improved}/{len(speedups)}")
        print(f"    Slower with heuristics : {slowed}/{len(speedups)}")


def report_solver_iterations(recs):
    section("Solver Iterations per Level (solved only)")
    configs = sorted(set(r["config"] for r in recs))

    header = f"  {'Config':<35}  {'median':>8}  {'mean':>8}  {'max':>8}"
    print(header)
    print("  " + "-" * (len(header) - 2))

    for cfg in configs:
        solved = [r for r in recs if r["config"] == cfg and r["solved"]]
        iters = [solver_iterations(r) for r in solved]
        if not iters:
            continue
        print(
            f"  {cfg:<35}  "
            f"{fmt(median(iters)):>8}  {fmt(mean(iters)):>8}  {max(iters):>8}"
        )


def report_stuck(recs):
    section("Stuck Levels (not solved, no error, no timeout)")
    configs = sorted(set(r["config"] for r in recs))
    for cfg in configs:
        stuck = [r for r in recs if r["config"] == cfg and not r["solved"]
                 and not r["error"] and not r["timed_out"]]
        if not stuck:
            continue
        print(f"\n  {cfg}  ({len(stuck)} stuck)")
        cats = Counter(r["category"] for r in stuck)
        print(f"    By category: {dict(cats)}")
        for r in sorted(stuck, key=lambda x: x["category"]):
            det = r["determined"] or 0
            tot = r["total"] or 1
            print(f"    {r['category']:>6}  {det:>3}/{tot:<3}  {r['name']}")


def report_category_timing(recs):
    section("Solve Time by Category (solved only, all configs combined)")
    categories = ["small", "medium", "large"]
    for cat in categories:
        times = [r["elapsed_s"] for r in recs if r["category"] == cat and r["solved"]]
        if not times:
            continue
        print(
            f"  {cat:<8}  n={len(times):>4}  "
            f"median={fmt(median(times))}s  "
            f"mean={fmt(mean(times))}s  "
            f"max={fmt(max(times))}s"
        )


# ---------------------------------------------------------------------------
# Plots
# ---------------------------------------------------------------------------

def make_plots(recs, plots_dir: str):
    import matplotlib.pyplot as plt
    import numpy as np

    os.makedirs(plots_dir, exist_ok=True)

    configs = sorted(set(r["config"] for r in recs))
    colors = {"small": "#4CAF50", "medium": "#2196F3", "large": "#F44336"}

    # 1. Solve time distribution per config (violin)
    fig, axes = plt.subplots(1, len(configs), figsize=(5 * len(configs), 5), sharey=True)
    if len(configs) == 1:
        axes = [axes]
    for ax, cfg in zip(axes, configs):
        data_by_cat = {}
        for cat in ["small", "medium", "large"]:
            times = [r["elapsed_s"] for r in recs if r["config"] == cfg
                     and r["category"] == cat and r["solved"]]
            if times:
                data_by_cat[cat] = times
        labels = list(data_by_cat.keys())
        vp = ax.violinplot([data_by_cat[l] for l in labels], showmedians=True)
        for patch, lbl in zip(vp["bodies"], labels):
            patch.set_facecolor(colors[lbl])
            patch.set_alpha(0.7)
        ax.set_xticks(range(1, len(labels) + 1))
        ax.set_xticklabels(labels)
        ax.set_yscale("log")
        ax.set_title(cfg, fontsize=8)
        ax.set_ylabel("Solve time (s)" if ax == axes[0] else "")
    fig.suptitle("Solve Time Distribution by Config and Category")
    fig.tight_layout()
    fig.savefig(os.path.join(plots_dir, "solve_time_violin.png"), dpi=150)
    plt.close(fig)

    # 2. Heuristic fraction histogram (for h=pspr,ac3 config)
    h_cfg = "h=pspr,ac3;s=gurobi;M=100"
    h_solved = [r for r in recs if r["config"] == h_cfg and r["solved"]]
    if h_solved:
        fracs = [heuristic_cells(r) / r["total"] for r in h_solved]
        fig, ax = plt.subplots(figsize=(7, 4))
        ax.hist(fracs, bins=20, color="#2ECC71", edgecolor="black", alpha=0.8)
        ax.axvline(median(fracs), color="red", linestyle="--", label=f"median={median(fracs)*100:.1f}%")
        ax.set_xlabel("Fraction of cells forced by heuristics")
        ax.set_ylabel("Number of levels")
        ax.set_title(f"Heuristic Cell Contribution — {h_cfg}")
        ax.legend()
        fig.tight_layout()
        fig.savefig(os.path.join(plots_dir, "heuristic_fraction.png"), dpi=150)
        plt.close(fig)

    # 3. Speedup scatter: cells vs speedup
    baseline_cfg = "h=none;s=gurobi;M=100"
    baseline = {r["level_path"]: r for r in recs if r["config"] == baseline_cfg and r["solved"]}
    h_recs = [r for r in recs if r["config"] == h_cfg and r["solved"]]
    pairs = []
    for r in h_recs:
        b = baseline.get(r["level_path"])
        if b and b["elapsed_s"] and r["elapsed_s"]:
            pairs.append((r["total"], b["elapsed_s"] / r["elapsed_s"], r["category"]))

    if pairs:
        fig, ax = plt.subplots(figsize=(7, 5))
        for cat in ["small", "medium", "large"]:
            pts = [(x, y) for x, y, c in pairs if c == cat]
            if pts:
                xs, ys = zip(*pts)
                ax.scatter(xs, ys, label=cat, color=colors[cat], alpha=0.6, s=30)
        ax.axhline(1.0, color="black", linestyle="--", linewidth=0.8, label="no speedup")
        ax.set_xlabel("Level size (cells)")
        ax.set_ylabel("Speedup (×)")
        ax.set_title(f"Heuristic Speedup vs Level Size\n({h_cfg} vs {baseline_cfg})")
        ax.legend()
        fig.tight_layout()
        fig.savefig(os.path.join(plots_dir, "speedup_scatter.png"), dpi=150)
        plt.close(fig)

    # 4. Solver iterations per level (box plot by config)
    fig, ax = plt.subplots(figsize=(8, 4))
    iter_data = []
    iter_labels = []
    for cfg in configs:
        solved = [r for r in recs if r["config"] == cfg and r["solved"]]
        iters = [solver_iterations(r) for r in solved]
        if iters:
            iter_data.append(iters)
            iter_labels.append(cfg.replace("h=", "h=\n").replace(";s=", "\ns="))
    ax.boxplot(iter_data, labels=iter_labels, patch_artist=True)
    ax.set_ylabel("Solver iterations per level")
    ax.set_title("Solver Iterations per Solved Level")
    fig.tight_layout()
    fig.savefig(os.path.join(plots_dir, "solver_iterations.png"), dpi=150)
    plt.close(fig)

    print(f"\n  Saved plots to {plots_dir}/")
    for f in sorted(os.listdir(plots_dir)):
        print(f"    {f}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--runs-file", default="testing/runs.jsonl")
    p.add_argument("--plots", action="store_true", help="Generate and save plots.")
    args = p.parse_args()

    _REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    runs_file = os.path.join(_REPO_ROOT, args.runs_file)

    recs = load_records(runs_file)

    report_overview(recs)
    report_solve_rates(recs)
    report_timing(recs)
    report_category_timing(recs)
    report_heuristic_contribution(recs)
    report_speedup(recs)
    report_solver_iterations(recs)
    report_stuck(recs)

    if args.plots:
        plots_dir = os.path.join(os.path.dirname(runs_file), "plots")
        make_plots(recs, plots_dir)


if __name__ == "__main__":
    main()
