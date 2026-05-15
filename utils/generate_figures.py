"""Generate figures for report.typ from testing/runs.jsonl.

Outputs to figures/ (PNG, 300 dpi). Headless matplotlib.
"""

import json
import os
import statistics
import sys
from collections import defaultdict
from typing import Dict, List

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIG_DIR = os.path.join(_REPO_ROOT, "figures")
RUNS_FILE = os.path.join(_REPO_ROOT, "testing/runs.jsonl")

# Color-blind safe palette (Wong, 2011)
PALETTE = {
    "gurobi":     "#0072B2",
    "z3":         "#D55E00",
    "z3_qffd":    "#E69F00",
    "z3_assume":  "#F0E442",
    "rust":       "#009E73",
    "none":       "#56B4E9",
}
TIER_ORDER = ["small", "medium", "large"]


def load_runs():
    rows = []
    with open(RUNS_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def parse_cfg(cfg: str):
    """h=...;s=...;M=...  →  (heur_str, solver, M)"""
    parts = dict(p.split("=", 1) for p in cfg.split(";"))
    return parts.get("h", ""), parts.get("s", ""), parts.get("M", "")


def by_config(rows):
    out = defaultdict(list)
    for r in rows:
        out[r["config"]].append(r)
    return out


# ---------------------------------------------------------------------------
# 1) Coverage bar chart
# ---------------------------------------------------------------------------

def fig_coverage(rows):
    bcfg = by_config(rows)
    solvers = ["gurobi", "z3", "z3_qffd", "rust"]
    heuristic_modes = [("h=none", "no heuristics"),
                       ("h=pspr,ac3", "+ pspr,ac3")]

    fig, axes = plt.subplots(1, 3, figsize=(11, 3.6), sharey=False)
    width = 0.35
    tiers = TIER_ORDER
    tier_totals = {}
    for tier in tiers:
        tier_totals[tier] = max(
            (len([r for r in rs if r["category"] == tier])
             for rs in bcfg.values()), default=0)

    for ax, tier in zip(axes, tiers):
        x = np.arange(len(solvers))
        for i, (hkey, hlabel) in enumerate(heuristic_modes):
            counts = []
            for s in solvers:
                cfg = f"{hkey};s={s};M={'na' if s=='rust' else '100'}"
                rs = [r for r in bcfg.get(cfg, []) if r["category"] == tier]
                counts.append(sum(1 for r in rs if r.get("solved")))
            offset = (i - 0.5) * width
            bars = ax.bar(x + offset, counts, width, label=hlabel,
                          color=[PALETTE[s] for s in solvers],
                          alpha=1.0 if i == 0 else 0.55,
                          edgecolor="black", linewidth=0.4)
            for j, b in enumerate(bars):
                if counts[j] > 0:
                    ax.text(b.get_x() + b.get_width()/2, b.get_height()+0.3,
                            f"{counts[j]}", ha="center", va="bottom", fontsize=7)
        # Heuristics-only baseline as a horizontal line
        cfg = "h=pspr,ac3;s=none;M=100"
        rs = [r for r in bcfg.get(cfg, []) if r["category"] == tier]
        h_only = sum(1 for r in rs if r.get("solved"))
        ax.axhline(h_only, color=PALETTE["none"], linestyle="--", linewidth=1,
                   label=f"heur-only ({h_only})")

        total = tier_totals[tier]
        ax.set_title(f"{tier}  (total = {total})")
        ax.set_xticks(x)
        ax.set_xticklabels(solvers, rotation=0, fontsize=8)
        ax.set_ylabel("levels solved")
        ax.set_ylim(0, max(total, 1) * 1.12)
        ax.grid(axis="y", alpha=0.3)

    # Shared legend in the first axes; only show distinct entries
    handles, labels = axes[0].get_legend_handles_labels()
    seen = set(); uniq_h, uniq_l = [], []
    for h, l in zip(handles, labels):
        if l not in seen:
            seen.add(l); uniq_h.append(h); uniq_l.append(l)
    axes[0].legend(uniq_h, uniq_l, fontsize=7, loc="lower right")

    fig.suptitle("Coverage by solver and difficulty tier (60s timeout)")
    fig.tight_layout()
    out = os.path.join(FIG_DIR, "coverage_bar.png")
    fig.savefig(out, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out}")


# ---------------------------------------------------------------------------
# 2) Empirical CDF of solve times
# ---------------------------------------------------------------------------

def fig_time_cdf(rows):
    bcfg = by_config(rows)
    configs = [
        ("h=none;s=gurobi;M=100",  "Gurobi"),
        ("h=none;s=z3;M=100",      "Z3 (PbEq)"),
        ("h=none;s=z3_qffd;M=100", "Z3-QFFD"),
        ("h=none;s=rust;M=na",     "Rust ref-solver"),
    ]

    fig, ax = plt.subplots(figsize=(7, 4))
    n_total = max((len(bcfg.get(c, [])) for c, _ in configs), default=0)
    for cfg, label in configs:
        rs = bcfg.get(cfg, [])
        times = sorted(r["elapsed_s"] for r in rs if r.get("solved"))
        if not times:
            continue
        # Step CDF: x = times, y = fraction of *total levels* solved by t
        denom = max(len(rs), 1)
        ys = [(i+1)/denom for i in range(len(times))]
        color_key = cfg.split("s=")[1].split(";")[0]
        ax.step(times, ys, where="post", label=f"{label} ({len(times)}/{denom})",
                color=PALETTE.get(color_key, "black"), linewidth=1.8)
    ax.set_xscale("log")
    ax.set_xlim(0.001, 80)
    ax.set_ylim(0, 1.0)
    ax.set_xlabel("solve time (s, log scale)")
    ax.set_ylabel("fraction of levels solved")
    ax.set_title("Empirical CDF of per-level solve time (h=none, 60s timeout)")
    ax.grid(True, alpha=0.3, which="both")
    ax.legend(loc="lower right", fontsize=8)
    fig.tight_layout()
    out = os.path.join(FIG_DIR, "time_cdf.png")
    fig.savefig(out, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out}")


# ---------------------------------------------------------------------------
# 3) Gurobi vs Z3 scatter (log-log)
# ---------------------------------------------------------------------------

def fig_gurobi_vs_z3(rows):
    bcfg = by_config(rows)
    g = {r["level_path"]: r for r in bcfg.get("h=none;s=gurobi;M=100", []) if r.get("solved")}
    z = {r["level_path"]: r for r in bcfg.get("h=none;s=z3;M=100", []) if r.get("solved")}
    shared = sorted(set(g) & set(z))

    colors_by_tier = {"small": "#56B4E9", "medium": "#E69F00", "large": "#D55E00"}
    outlier_names = {
        "modulo-mediumhard", "sorcerer", "missing-some-information",
        "play", "its-hexcells-oclock",
    }

    fig, ax = plt.subplots(figsize=(6.5, 5.5))
    for tier in TIER_ORDER:
        xs, ys, labels = [], [], []
        for lp in shared:
            if g[lp]["category"] != tier:
                continue
            x = max(g[lp]["elapsed_s"], 1e-3)
            y = max(z[lp]["elapsed_s"], 1e-3)
            xs.append(x); ys.append(y); labels.append(lp)
        ax.scatter(xs, ys, s=18, alpha=0.55,
                   color=colors_by_tier[tier], label=f"{tier} ({len(xs)})",
                   edgecolor="none")

    # Diagonal
    lo, hi = 1e-3, 1e2
    ax.plot([lo, hi], [lo, hi], "k--", linewidth=0.8, alpha=0.6, label="x=y")
    ax.plot([lo, hi], [10*lo, 10*hi], "k:", linewidth=0.6, alpha=0.4)
    ax.plot([lo, hi], [100*lo, 100*hi], "k:", linewidth=0.4, alpha=0.3)

    # Label outliers (which are by name in shared paths)
    for lp in shared:
        slug = os.path.basename(os.path.dirname(lp))
        if slug in outlier_names:
            x = max(g[lp]["elapsed_s"], 1e-3); y = max(z[lp]["elapsed_s"], 1e-3)
            ax.annotate(slug, (x, y), fontsize=6,
                        xytext=(4, 3), textcoords="offset points")

    # Also annotate Z3 timeouts on solved-by-Gurobi
    only_g = [lp for lp in g if lp not in z]
    for lp in only_g[:30]:
        slug = os.path.basename(os.path.dirname(lp))
        x = max(g[lp]["elapsed_s"], 1e-3)
        ax.scatter([x], [60], marker="^", color="red", s=22, alpha=0.7,
                   edgecolor="none")

    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlim(1e-3, 1e2); ax.set_ylim(1e-3, 1e2)
    ax.set_xlabel("Gurobi elapsed (s)")
    ax.set_ylabel("Z3 elapsed (s)")
    ax.set_title("Per-level comparison: Gurobi vs Z3 (no heuristics)")
    ax.grid(True, alpha=0.3, which="both")
    ax.legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    out = os.path.join(FIG_DIR, "gurobi_vs_z3_scatter.png")
    fig.savefig(out, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out}")


# ---------------------------------------------------------------------------
# 4) Cell count vs solve time
# ---------------------------------------------------------------------------

def fig_cells_vs_time(rows):
    bcfg = by_config(rows)
    configs = [
        ("h=none;s=gurobi;M=100",  "Gurobi",         PALETTE["gurobi"]),
        ("h=none;s=z3;M=100",      "Z3 (PbEq)",      PALETTE["z3"]),
        ("h=none;s=z3_qffd;M=100", "Z3-QFFD",        PALETTE["z3_qffd"]),
        ("h=none;s=rust;M=na",     "Rust ref-solver",PALETTE["rust"]),
    ]

    fig, axes = plt.subplots(2, 2, figsize=(9.5, 6.5), sharex=True, sharey=True)
    axes = axes.flatten()
    for ax, (cfg, label, color) in zip(axes, configs):
        rs = [r for r in bcfg.get(cfg, []) if r.get("solved")
              and (r.get("cells") or r.get("total"))]
        xs = [r.get("cells") or r.get("total") for r in rs]
        ys = [max(r["elapsed_s"], 1e-3) for r in rs]
        ax.scatter(xs, ys, s=12, color=color, alpha=0.5, edgecolor="none")
        ax.set_yscale("log")
        ax.set_xlabel("cells in level")
        ax.set_ylabel("solve time (s)")
        ax.set_title(f"{label}  ({len(rs)} solved)")
        ax.grid(True, alpha=0.3, which="both")
        ax.set_ylim(1e-3, 1e2)

    fig.suptitle("Solve time vs puzzle size")
    fig.tight_layout()
    out = os.path.join(FIG_DIR, "cells_vs_time.png")
    fig.savefig(out, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out}")


# ---------------------------------------------------------------------------
# 5) Heuristics attribution stacked bar
# ---------------------------------------------------------------------------

def fig_heuristics_attribution(rows):
    bcfg = by_config(rows)
    heur = {r["level_path"]: r for r in bcfg.get("h=pspr,ac3;s=none;M=100", [])}
    gur  = {r["level_path"]: r for r in bcfg.get("h=none;s=gurobi;M=100", [])}

    # Per tier: heur-only, both, gurobi-only, neither (where parseable)
    tiers = TIER_ORDER
    cats = {t: {"heur_only": 0, "both": 0, "gur_only": 0, "neither": 0,
                "total": 0} for t in tiers}
    for lp in set(heur) | set(gur):
        h_r = heur.get(lp); g_r = gur.get(lp)
        ref = h_r or g_r
        if ref is None or ref.get("error") and not ref.get("timed_out"):
            continue
        tier = ref["category"]
        if tier not in cats:
            continue
        cats[tier]["total"] += 1
        h_solved = bool(h_r and h_r.get("solved"))
        g_solved = bool(g_r and g_r.get("solved"))
        if h_solved and g_solved:
            cats[tier]["both"] += 1
        elif h_solved:
            cats[tier]["heur_only"] += 1
        elif g_solved:
            cats[tier]["gur_only"] += 1
        else:
            cats[tier]["neither"] += 1

    fig, ax = plt.subplots(figsize=(7, 4))
    bottoms = np.zeros(len(tiers))
    series = [
        ("both",       "solved by both heur+solver", "#009E73"),
        ("heur_only",  "solved by heuristics only",  "#56B4E9"),
        ("gur_only",   "solved by Gurobi only",      "#D55E00"),
        ("neither",    "unsolved by either",          "#888888"),
    ]
    for key, label, color in series:
        vals = np.array([cats[t][key] for t in tiers], dtype=float)
        ax.bar(tiers, vals, bottom=bottoms, color=color, label=label,
               edgecolor="black", linewidth=0.4)
        for i, v in enumerate(vals):
            if v > 0:
                ax.text(i, bottoms[i] + v/2, f"{int(v)}",
                        ha="center", va="center", fontsize=8,
                        color="white" if key in ("gur_only", "both") else "black")
        bottoms += vals
    ax.set_ylabel("levels (parseable)")
    ax.set_title("Heuristic attribution vs Gurobi (per tier)")
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    out = os.path.join(FIG_DIR, "heuristics_attribution.png")
    fig.savefig(out, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out}")


# ---------------------------------------------------------------------------
# 6) Puzzle screenshot via project/viz/visualize.py
# ---------------------------------------------------------------------------

def fig_puzzle_screenshot():
    sys.path.insert(0, _REPO_ROOT)
    from project.viz.visualize import visualize_level
    level_path = os.path.join(_REPO_ROOT, "levels/medium/tametsi-tmi/level.hexcells")
    out = os.path.join(FIG_DIR, "puzzle_screenshot.png")
    visualize_level(level_path, out)
    print(f"wrote {out}")


def main():
    os.makedirs(FIG_DIR, exist_ok=True)
    rows = load_runs()
    print(f"Loaded {len(rows)} runs from {RUNS_FILE}")
    fig_coverage(rows)
    fig_time_cdf(rows)
    fig_gurobi_vs_z3(rows)
    fig_cells_vs_time(rows)
    fig_heuristics_attribution(rows)
    fig_puzzle_screenshot()


if __name__ == "__main__":
    main()
