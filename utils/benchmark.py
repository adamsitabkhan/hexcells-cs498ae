"""Benchmark runner for the modular Hexcells solver.

Runs all levels (or a filtered subset) with a given solver configuration and
writes one JSONL record per level to `project/runs.jsonl`.

Each record format:
  {
    "level_path": "levels/small/...",
    "name": "...",
    "author": "...",
    "category": "small|medium|large",
    "cells": 42,
    "config": "h=pspr,ac3;s=gurobi;M=100",
    "timestamp": "2026-05-13T...",
    "elapsed_s": 1.23,
    "determined": 42,
    "total": 42,
    "accuracy": 42,
    "solved": true,
    "timed_out": false,
    "error": null,
    "cycles": [
      {
        "cycle": 1,
        "heuristic_steps": [
          {"module": "pspr", "cells_forced": 3, "known_after": 10},
          ...
        ],
        "solver_steps": [
          {"module": "gurobi", "iteration": 1, "cells_forced": 5, "known_after": 15},
          ...
        ]
      },
      ...
    ]
  }

CLI usage:
    python -m utils.benchmark \\
        [--heuristics pspr,ac3] [--solver gurobi|z3] [-M 100] \\
        [--timeout 60] [--parallel 4] [--no-resume] \\
        [--levels-dir levels] [--runs-file project/runs.jsonl] \\
        [--category small|medium|large] [-v]
"""

import argparse
import json
import multiprocessing
import os
import sys
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple

# Ensure repo root is on sys.path so project.* imports work from utils/
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from project.lib.parser import Problem, parse_hexcells
from project.solve import run


# ---------------------------------------------------------------------------
# Config key
# ---------------------------------------------------------------------------

def make_config_key(heuristics: List[str], solver: Optional[str], M: int) -> str:
    h = ",".join(heuristics) if heuristics else "none"
    s = solver or "none"
    return f"h={h};s={s};M={M}"


# ---------------------------------------------------------------------------
# Level discovery
# ---------------------------------------------------------------------------

def find_levels(levels_dir: str, category_filter: Optional[str] = None) -> List[Dict]:
    """Return list of level metadata dicts, one per level.hexcells file.

    Drives from index.json when present (keyed by hash, path field like
    'small/slug-name'). Falls back to directory scan for unindexed levels.
    """
    index_path = os.path.join(levels_dir, "index.json")
    levels = []
    seen_paths: Set[str] = set()

    if os.path.exists(index_path):
        with open(index_path) as f:
            index = json.load(f)
        for entry in index.values():
            cat = entry.get("category", "")
            if category_filter and cat != category_filter:
                continue
            # index path is like "small/slug-name" (relative to levels_dir)
            rel_to_levels = entry["path"]
            abs_path = os.path.join(levels_dir, rel_to_levels, "level.hexcells")
            if not os.path.exists(abs_path):
                continue
            rel_path = os.path.relpath(abs_path, _REPO_ROOT)
            seen_paths.add(rel_path)
            levels.append({
                "path": rel_path,
                "abs_path": abs_path,
                "name": entry.get("name", rel_to_levels),
                "author": entry.get("author", ""),
                "category": cat,
                "cells": entry.get("cells"),
            })

    # Scan for any level.hexcells files not covered by the index
    categories = ["small", "medium", "large"]
    if category_filter:
        categories = [c for c in categories if c == category_filter]
    for cat in categories:
        cat_dir = os.path.join(levels_dir, cat)
        if not os.path.isdir(cat_dir):
            continue
        for slug in sorted(os.listdir(cat_dir)):
            abs_path = os.path.join(cat_dir, slug, "level.hexcells")
            if not os.path.exists(abs_path):
                continue
            rel_path = os.path.relpath(abs_path, _REPO_ROOT)
            if rel_path in seen_paths:
                continue
            levels.append({
                "path": rel_path,
                "abs_path": abs_path,
                "name": slug,
                "author": "",
                "category": cat,
                "cells": None,
            })

    levels.sort(key=lambda x: (x["category"], x["name"]))
    return levels


# ---------------------------------------------------------------------------
# Resume support
# ---------------------------------------------------------------------------

def load_done(runs_file: str, config_key: str) -> Set[str]:
    """Return set of level paths already recorded for this config."""
    done = set()
    if not os.path.exists(runs_file):
        return done
    with open(runs_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if rec.get("config") == config_key:
                    done.add(rec["level_path"])
            except json.JSONDecodeError:
                continue
    return done


# ---------------------------------------------------------------------------
# Stats → nested cycles
# ---------------------------------------------------------------------------

def build_cycles(stats: List[Dict]) -> List[Dict]:
    """Convert flat stats list from solve.run() into nested cycle structure."""
    cycles: Dict[int, Dict] = {}
    for entry in stats:
        c = entry["cycle"]
        if c not in cycles:
            cycles[c] = {"cycle": c, "heuristic_steps": [], "solver_steps": []}
        if entry["phase"] == "heuristic":
            cycles[c]["heuristic_steps"].append({
                "module": entry["module"],
                "cells_forced": entry["cells_forced"],
                "known_after": entry["known_after"],
            })
        else:
            cycles[c]["solver_steps"].append({
                "module": entry["module"],
                "iteration": entry["iteration"],
                "cells_forced": entry["cells_forced"],
                "known_after": entry["known_after"],
            })
    return [cycles[k] for k in sorted(cycles)]


# ---------------------------------------------------------------------------
# Worker (runs in a subprocess for timeout support)
# ---------------------------------------------------------------------------

def _worker(
    queue: multiprocessing.Queue,
    abs_path: str,
    heuristic_names: List[str],
    solver_name: Optional[str],
    M: int,
):
    try:
        level = parse_hexcells(abs_path)
        problem = Problem(level)
        stats = []
        t0 = time.time()
        state = run(problem, heuristic_names, solver_name, M, verbose=False, stats=stats)
        elapsed = time.time() - t0

        known = len(state.known)
        total = len(problem.cells)
        accuracy = sum(
            1 for c, is_mine in state.known.items()
            if is_mine == (c in problem.mines)
        )
        queue.put({
            "elapsed_s": elapsed,
            "determined": known,
            "total": total,
            "accuracy": accuracy,
            "solved": state.is_complete(),
            "cycles": build_cycles(stats),
            "error": None,
        })
    except Exception as e:
        queue.put({"error": str(e)})


def run_level(
    abs_path: str,
    heuristic_names: List[str],
    solver_name: Optional[str],
    M: int,
    timeout_s: float,
) -> Dict:
    """Run one level in a subprocess with a hard timeout."""
    queue: multiprocessing.Queue = multiprocessing.Queue()
    p = multiprocessing.Process(
        target=_worker,
        args=(queue, abs_path, heuristic_names, solver_name, M),
        daemon=True,
    )
    p.start()
    p.join(timeout_s)

    if p.is_alive():
        p.terminate()
        p.join()
        return {"timed_out": True, "error": f"Exceeded {timeout_s}s timeout"}

    if queue.empty():
        return {"timed_out": False, "error": "Worker exited without result"}

    result = queue.get_nowait()
    result.setdefault("timed_out", False)
    return result


# ---------------------------------------------------------------------------
# Record helpers
# ---------------------------------------------------------------------------

def make_record(
    meta: Dict,
    config_key: str,
    result: Dict,
) -> Dict:
    return {
        "level_path": meta["path"],
        "name": meta["name"],
        "author": meta["author"],
        "category": meta["category"],
        "cells": meta.get("cells"),
        "config": config_key,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "elapsed_s": result.get("elapsed_s"),
        "determined": result.get("determined"),
        "total": result.get("total"),
        "accuracy": result.get("accuracy"),
        "solved": result.get("solved", False),
        "timed_out": result.get("timed_out", False),
        "error": result.get("error"),
        "cycles": result.get("cycles", []),
    }


def write_record(runs_file: str, record: Dict):
    os.makedirs(os.path.dirname(os.path.abspath(runs_file)), exist_ok=True)
    with open(runs_file, "a") as f:
        f.write(json.dumps(record) + "\n")


def print_progress(i: int, total: int, meta: Dict, result: Dict, verbose: bool):
    name = meta["name"] or meta["path"]
    cat = meta["category"]
    cells = meta.get("cells") or result.get("total", "?")
    if result.get("timed_out"):
        status = "TIMEOUT"
    elif result.get("error"):
        status = f"ERROR: {result['error']}"
    elif result.get("solved"):
        status = f"solved in {result['elapsed_s']:.3f}s"
    else:
        det = result.get("determined", 0)
        tot = result.get("total", 1)
        status = f"stuck {det}/{tot} in {result.get('elapsed_s', 0):.3f}s"
    print(f"  [{i}/{total}] {cat}/{name} ({cells} cells) — {status}")


# ---------------------------------------------------------------------------
# Parallel execution
# ---------------------------------------------------------------------------

def run_parallel(
    levels: List[Dict],
    skip: Set[str],
    heuristic_names: List[str],
    solver_name: Optional[str],
    M: int,
    timeout_s: float,
    n_workers: int,
    runs_file: str,
    config_key: str,
    verbose: bool,
):
    from concurrent.futures import ThreadPoolExecutor, as_completed

    todo = [lv for lv in levels if lv["path"] not in skip]
    total = len(todo)
    print(f"Running {total} levels with {n_workers} workers...")

    completed = 0

    def task(meta):
        return meta, run_level(meta["abs_path"], heuristic_names, solver_name, M, timeout_s)

    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        futures = {pool.submit(task, meta): meta for meta in todo}
        for fut in as_completed(futures):
            meta, result = fut.result()
            completed += 1
            record = make_record(meta, config_key, result)
            write_record(runs_file, record)
            print_progress(completed, total, meta, result, verbose)


def run_sequential(
    levels: List[Dict],
    skip: Set[str],
    heuristic_names: List[str],
    solver_name: Optional[str],
    M: int,
    timeout_s: float,
    runs_file: str,
    config_key: str,
    verbose: bool,
):
    todo = [lv for lv in levels if lv["path"] not in skip]
    total = len(todo)
    print(f"Running {total} levels sequentially...")

    for i, meta in enumerate(todo, 1):
        result = run_level(meta["abs_path"], heuristic_names, solver_name, M, timeout_s)
        record = make_record(meta, config_key, result)
        write_record(runs_file, record)
        print_progress(i, total, meta, result, verbose)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(
        prog="python -m utils.benchmark",
        description="Benchmark the modular Hexcells solver across all levels.",
    )
    p.add_argument(
        "--heuristics", default="",
        help="Comma-separated heuristics in order (choices: pspr, ac3). Empty = none.",
    )
    p.add_argument(
        "--solver", default=None,
        choices=["gurobi", "z3", "z3_assume", "z3_qffd"],
        help="Optional full solver.",
    )
    p.add_argument("-M", "--iterations", type=int, default=100,
                   help="Max solver iterations per cycle (default 100).")
    p.add_argument("--timeout", type=float, default=60.0,
                   help="Per-level timeout in seconds (default 60).")
    p.add_argument("--parallel", type=int, default=1,
                   help="Number of parallel workers (default 1 = sequential).")
    p.add_argument("--no-resume", action="store_true",
                   help="Re-run levels already in the runs file.")
    p.add_argument("--levels-dir", default="levels",
                   help="Path to the levels directory (default: levels).")
    p.add_argument("--runs-file", default="testing/runs.jsonl",
                   help="Path to the output JSONL file (default: testing/runs.jsonl).")
    p.add_argument("--category", choices=["small", "medium", "large"],
                   help="Restrict to one size category.")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    heuristic_names = [s.strip().lower() for s in args.heuristics.split(",") if s.strip()]
    if not heuristic_names and not args.solver:
        p.error("Must specify at least one --heuristics and/or --solver.")

    config_key = make_config_key(heuristic_names, args.solver, args.iterations)
    print(f"Config: {config_key}  timeout={args.timeout}s  parallel={args.parallel}")

    levels_dir = os.path.join(_REPO_ROOT, args.levels_dir)
    levels = find_levels(levels_dir, args.category)
    if not levels:
        print(f"No levels found in {levels_dir}")
        sys.exit(1)
    print(f"Found {len(levels)} levels.")

    runs_file = os.path.join(_REPO_ROOT, args.runs_file)
    skip: Set[str] = set()
    if not args.no_resume:
        skip = load_done(runs_file, config_key)
        if skip:
            print(f"Resuming: {len(skip)} already done, skipping.")

    if args.parallel > 1:
        run_parallel(
            levels, skip, heuristic_names, args.solver, args.iterations,
            args.timeout, args.parallel, runs_file, config_key, args.verbose,
        )
    else:
        run_sequential(
            levels, skip, heuristic_names, args.solver, args.iterations,
            args.timeout, runs_file, config_key, args.verbose,
        )

    print(f"\nDone. Results appended to {args.runs_file}")


if __name__ == "__main__":
    main()
