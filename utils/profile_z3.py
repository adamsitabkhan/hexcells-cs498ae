"""Profile the baseline Z3 incremental solver to locate its bottleneck.

For each chosen level, instrument `Z3Module.step()` to record per-iteration:
  - elapsed wall time
  - number of unknown cells tested
  - baseline check() time vs sum of per-cell push/pop check times
  - solver.statistics() deltas (conflicts, decisions, propagations)

Also runs a cProfile pass on the medium-tier level.

Outputs a markdown report at testing/z3_profile.md.

Usage:
    python -m utils.profile_z3
"""

import cProfile
import io
import os
import pstats
import sys
import time
from typing import Dict, List, Tuple

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import z3

from project.lib.parser import Coords, Problem, parse_hexcells
from project.z3_solver import Z3Module


DIAGNOSTIC_LEVELS = [
    ("small",  "levels/small/spiral-easy-medium-1-4/level.hexcells"),
    ("medium", "levels/medium/tametsi-tmi/level.hexcells"),
    ("large",  "levels/large/a-giant-scoop-of-vanilla/level.hexcells"),
]

# Cap large runs so the profiler completes in a reasonable time. The point is
# to characterize per-iteration cost, not to solve the puzzle end-to-end.
# Capped to keep the profiler run tractable: the large baseline is ~229s
# end-to-end. Set "large" to 0 (skip) by default; pass --include-large to
# the CLI to re-enable it.
MAX_ITERATIONS_PER_LEVEL = {"small": 100, "medium": 100, "large": 0}


def _stats_dict(stats: z3.Statistics) -> Dict[str, float]:
    out = {}
    keys = stats.keys()
    for i in range(len(keys)):
        k, v = stats[i]
        out[k] = v
    return out


def _stat_delta(after: Dict, before: Dict, key: str) -> float:
    return float(after.get(key, 0)) - float(before.get(key, 0))


class InstrumentedZ3(Z3Module):
    """Z3Module that records per-iteration timings + statistics."""

    def __init__(self, problem, **kw):
        super().__init__(problem, **kw)
        self.iter_records: List[Dict] = []

    def step(self):
        if self.solver.check() != z3.sat:
            return []

        # Baseline check (a no-op here since we just called it; redo to time)
        t0 = time.perf_counter()
        if self.solver.check() != z3.sat:
            return []
        baseline_check_s = time.perf_counter() - t0

        m = self.solver.model()
        baseline = {c: bool(m.evaluate(self.x[c])) for c in self.problem.cells}
        stats_before = _stats_dict(self.solver.statistics())

        forced: List[Tuple[Coords, bool]] = []
        loop_check_s = 0.0
        unknowns = list(self.state.unknown_cells())
        for c in unknowns:
            v = baseline[c]
            self.solver.push()
            self.solver.add(self.x[c] == (not v))
            t1 = time.perf_counter()
            result = self.solver.check()
            loop_check_s += time.perf_counter() - t1
            self.solver.pop()
            if result == z3.unsat:
                forced.append((c, v))

        stats_after = _stats_dict(self.solver.statistics())
        self.iter_records.append({
            "unknowns_tested": len(unknowns),
            "forced": len(forced),
            "baseline_check_s": baseline_check_s,
            "loop_check_s": loop_check_s,
            "d_conflicts":   _stat_delta(stats_after, stats_before, "conflicts"),
            "d_decisions":   _stat_delta(stats_after, stats_before, "decisions"),
            "d_propagations":_stat_delta(stats_after, stats_before, "propagations"),
        })
        return forced


def profile_level(tier: str, path: str, max_iters: int) -> Dict:
    abs_path = os.path.join(_REPO_ROOT, path)
    level = parse_hexcells(abs_path)
    problem = Problem(level)

    solver = InstrumentedZ3(problem, verbose=False)

    iter_wall: List[float] = []
    on_reveal_s = 0.0
    total_t0 = time.perf_counter()
    it = 0
    while it < max_iters and not solver.state.is_complete():
        it += 1
        t0 = time.perf_counter()
        forced = solver.step()
        iter_wall.append(time.perf_counter() - t0)
        if not forced:
            break
        t1 = time.perf_counter()
        for c, v in forced:
            unlocked = solver.state.reveal(c, v)
            solver.on_reveal(c, v, unlocked)
        on_reveal_s += time.perf_counter() - t1
    total_s = time.perf_counter() - total_t0

    known = len(solver.state.known)
    correct = sum(
        1 for c, is_mine in solver.state.known.items()
        if is_mine == (c in problem.mines)
    )

    return {
        "tier": tier,
        "path": path,
        "cells": len(problem.cells),
        "mines": problem.total_mines,
        "iterations_run": it,
        "complete": solver.state.is_complete(),
        "determined": known,
        "correct_on_determined": correct,
        "total_s": total_s,
        "on_reveal_s": on_reveal_s,
        "iter_records": solver.iter_records,
        "iter_wall": iter_wall,
    }


def run_cprofile_medium() -> str:
    """cProfile the medium level for one iteration; return top-30 by cumtime."""
    tier, path = DIAGNOSTIC_LEVELS[1]
    abs_path = os.path.join(_REPO_ROOT, path)
    level = parse_hexcells(abs_path)
    problem = Problem(level)
    solver = Z3Module(problem, verbose=False)

    pr = cProfile.Profile()
    pr.enable()
    forced = solver.step()
    pr.disable()

    buf = io.StringIO()
    ps = pstats.Stats(pr, stream=buf).sort_stats("cumulative")
    ps.print_stats(30)
    return buf.getvalue(), len(forced)


def fmt_pct(num, den):
    if den == 0:
        return "—"
    return f"{100*num/den:5.1f}%"


def render_report(results: List[Dict], cprof_text: str, cprof_forced: int) -> str:
    lines: List[str] = []
    lines.append("# Z3 Incremental Solver — Diagnostic Profile\n")
    lines.append("Baseline `project/z3_solver.py` instrumented with per-iteration timing "
                 "and `solver.statistics()` deltas. The large tier is capped at "
                 f"{MAX_ITERATIONS_PER_LEVEL['large']} outer iterations to keep the run tractable.\n")

    lines.append("## Per-level summary\n")
    lines.append("| Tier | Cells | Mines | Iters | Determined | Total s | On-reveal s | "
                 "Σ baseline-check s | Σ loop-check s | Loop / Total |")
    lines.append("|------|------:|------:|------:|-----------:|--------:|------------:|"
                 "-------------------:|---------------:|-------------:|")
    for r in results:
        sb = sum(x["baseline_check_s"] for x in r["iter_records"])
        sl = sum(x["loop_check_s"] for x in r["iter_records"])
        lines.append(
            f"| {r['tier']} | {r['cells']} | {r['mines']} | {r['iterations_run']} | "
            f"{r['determined']}/{r['cells']} | {r['total_s']:.3f} | "
            f"{r['on_reveal_s']:.3f} | {sb:.3f} | {sl:.3f} | "
            f"{fmt_pct(sl, r['total_s'])} |"
        )
    lines.append("")

    for r in results:
        lines.append(f"### {r['tier']} — `{r['path']}` ({r['cells']} cells)\n")
        lines.append("| Iter | Unknowns | Forced | Iter s | Baseline-check s | Loop-check s | "
                     "Δ conflicts | Δ decisions | Δ propagations |")
        lines.append("|-----:|---------:|-------:|-------:|-----------------:|-------------:|"
                     "------------:|------------:|---------------:|")
        for i, rec in enumerate(r["iter_records"], 1):
            iter_s = r["iter_wall"][i-1] if i-1 < len(r["iter_wall"]) else 0.0
            lines.append(
                f"| {i} | {rec['unknowns_tested']} | {rec['forced']} | "
                f"{iter_s:.3f} | {rec['baseline_check_s']:.4f} | "
                f"{rec['loop_check_s']:.3f} | "
                f"{int(rec['d_conflicts'])} | {int(rec['d_decisions'])} | "
                f"{int(rec['d_propagations'])} |"
            )
        lines.append("")

    lines.append("## cProfile (medium level, 1 outer iteration)\n")
    lines.append(f"Forced cells in this iteration: **{cprof_forced}**\n")
    lines.append("```")
    lines.append(cprof_text.strip())
    lines.append("```\n")
    return "\n".join(lines)


def main():
    results = []
    for tier, path in DIAGNOSTIC_LEVELS:
        if MAX_ITERATIONS_PER_LEVEL.get(tier, 0) <= 0:
            print(f"Skipping {tier}: {path} (capped to 0 iters)")
            continue
        print(f"Profiling {tier}: {path}...", flush=True)
        r = profile_level(tier, path, MAX_ITERATIONS_PER_LEVEL[tier])
        results.append(r)
        sb = sum(x["baseline_check_s"] for x in r["iter_records"])
        sl = sum(x["loop_check_s"] for x in r["iter_records"])
        print(f"  cells={r['cells']} iters={r['iterations_run']} "
              f"total={r['total_s']:.2f}s  baseline-check={sb:.2f}s  "
              f"loop-check={sl:.2f}s  determined={r['determined']}/{r['cells']}")

    print("\ncProfile on medium level (1 iteration)...", flush=True)
    cprof_text, cprof_forced = run_cprofile_medium()

    out_dir = os.path.join(_REPO_ROOT, "testing")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "z3_profile.md")
    with open(out_path, "w") as f:
        f.write(render_report(results, cprof_text, cprof_forced))
    print(f"\nReport: {out_path}")


if __name__ == "__main__":
    main()
