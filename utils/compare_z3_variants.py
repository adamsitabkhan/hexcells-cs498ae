"""Run baseline z3 + experiment variants on a few levels; print a comparison table.

Usage:
    python -m utils.compare_z3_variants \\
        [--levels small=...,medium=...,large=...] \\
        [--variants z3,z3_assume,z3_pbeq,z3_qffd] \\
        [--timeout 300]
"""

import argparse
import os
import sys
import time
from typing import Dict, List, Tuple

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from project.lib.parser import Problem, parse_hexcells
from project.solve import _load_solver


DEFAULT_LEVELS = [
    ("small",  "levels/small/spiral-easy-medium-1-4/level.hexcells"),
    ("medium", "levels/medium/tametsi-tmi/level.hexcells"),
    ("large",  "levels/large/a-giant-scoop-of-vanilla/level.hexcells"),
]

DEFAULT_VARIANTS = ["z3", "z3_assume", "z3_pbeq", "z3_qffd"]


def _worker(q, variant, abs_path):
    try:
        level = parse_hexcells(abs_path)
        problem = Problem(level)
        cls = _load_solver(variant)
        solver = cls(problem, verbose=False)
        t0 = time.perf_counter()
        solver.solve()
        elapsed = time.perf_counter() - t0
        known = len(solver.state.known)
        correct = sum(
            1 for c, is_mine in solver.state.known.items()
            if is_mine == (c in problem.mines)
        )
        q.put({
            "elapsed_s": elapsed,
            "determined": known,
            "total": len(problem.cells),
            "correct_on_determined": correct,
            "complete": solver.state.is_complete(),
            "error": None,
        })
    except Exception as e:
        q.put({"error": f"{type(e).__name__}: {e}"})


def run_one(variant: str, abs_path: str, timeout_s: float) -> Dict:
    import multiprocessing as mp

    q: mp.Queue = mp.Queue()
    p = mp.Process(target=_worker, args=(q, variant, abs_path), daemon=True)
    p.start()
    p.join(timeout_s)
    if p.is_alive():
        p.terminate()
        p.join()
        return {"timed_out": True, "error": f">{timeout_s}s"}
    if q.empty():
        return {"error": "worker exited without result"}
    out = q.get_nowait()
    out.setdefault("timed_out", False)
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--variants", default=",".join(DEFAULT_VARIANTS))
    p.add_argument("--timeout", type=float, default=300.0)
    p.add_argument("--skip-large", action="store_true",
                   help="Skip the large diagnostic level (baseline z3 is ~229s).")
    p.add_argument("--levels", default=None,
                   help="Comma-separated tier=path pairs; defaults to the 3 plan levels.")
    args = p.parse_args()

    if args.levels:
        levels = []
        for spec in args.levels.split(","):
            tier, path = spec.split("=", 1)
            levels.append((tier.strip(), path.strip()))
    else:
        levels = list(DEFAULT_LEVELS)
    if args.skip_large:
        levels = [lv for lv in levels if lv[0] != "large"]

    variants = [v.strip() for v in args.variants.split(",") if v.strip()]

    results: Dict[Tuple[str, str], Dict] = {}
    for tier, path in levels:
        abs_path = os.path.join(_REPO_ROOT, path)
        print(f"\n=== {tier}: {path} ===")
        for v in variants:
            print(f"  {v:12s} ...", end="", flush=True)
            r = run_one(v, abs_path, args.timeout)
            results[(tier, v)] = r
            if r.get("error"):
                print(f" ERROR: {r['error']}")
            else:
                tag = "OK" if r["complete"] else "stuck"
                print(f" {r['elapsed_s']:8.3f}s  det={r['determined']}/{r['total']}  "
                      f"correct={r['correct_on_determined']}/{r['determined']}  [{tag}]")

    print("\n## Summary table\n")
    header = "| Tier | Level | " + " | ".join(variants) + " |"
    sep = "|------|-------|" + "|".join(["------:"] * len(variants)) + "|"
    print(header); print(sep)
    for tier, path in levels:
        row = f"| {tier} | {os.path.basename(os.path.dirname(path))} |"
        for v in variants:
            r = results.get((tier, v), {})
            if r.get("error"):
                cell = f" {'TIMEOUT' if r.get('timed_out') else 'ERR'} "
            else:
                cell = f" {r['elapsed_s']:.2f}s "
                if not r["complete"]:
                    cell = cell.rstrip() + "*"
            row += cell + "|"
        print(row)
    print("\n(`*` = stuck before full solve)")


if __name__ == "__main__":
    main()
