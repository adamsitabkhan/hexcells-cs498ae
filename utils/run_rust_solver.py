"""Run the Rust reference-solver across the level corpus, writing JSONL records
into testing/runs.jsonl with the same schema as utils/benchmark.py.

The Rust binary at external/reference-solver/target/release/hexcells-solver
reads a .hexcells file on stdin and prints:
  line 1: "Solved steps:N max-local-difficulty:.. max-global-difficulty:.."
          or  "Requires additional rules"
          or  "Timeout"
  line 2: Debug-print of the Outcome enum

We classify by the first token of line 1 and wall-clock the subprocess
externally with a hard timeout.

Usage:
    python -m utils.run_rust_solver [--parallel 4] [--timeout 60] [--no-resume]
                                    [--levels-dir levels] [--runs-file testing/runs.jsonl]
                                    [--category small|medium|large]
"""

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Dict, Optional, Set

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from project.lib.parser import Problem, parse_hexcells
from utils.benchmark import find_levels, load_done, write_record


CONFIG_KEY = "h=none;s=rust;M=na"
RUST_BIN = os.path.join(_REPO_ROOT, "external/reference-solver/target/release/hexcells-solver")


def run_one(abs_path: str, timeout_s: float) -> Dict:
    if not os.path.isfile(RUST_BIN):
        return {"error": f"Rust binary not built at {RUST_BIN}"}
    try:
        with open(abs_path, "rb") as f:
            stdin_bytes = f.read()
    except OSError as e:
        return {"error": f"read {abs_path}: {e}"}

    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            [RUST_BIN, "-"],
            input=stdin_bytes,
            capture_output=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return {"timed_out": True, "elapsed_s": timeout_s,
                "error": f"Exceeded {timeout_s}s timeout"}
    elapsed = time.perf_counter() - t0

    stdout = proc.stdout.decode(errors="replace")
    stderr = proc.stderr.decode(errors="replace")
    first = stdout.splitlines()[0] if stdout else ""

    # Try to determine total cells from the parser (independent of Rust output)
    try:
        level = parse_hexcells(abs_path)
        problem = Problem(level)
        total = len(problem.cells)
    except Exception:
        total = None

    if proc.returncode != 0 and not first.startswith("Solved"):
        return {"elapsed_s": elapsed, "determined": 0, "total": total,
                "accuracy": 0, "solved": False, "timed_out": False,
                "error": (stderr.strip() or stdout.strip() or
                          f"exit {proc.returncode}")[:200]}

    if first.startswith("Solved"):
        # The reference-solver determines every cell when it returns Solved.
        det = total if total is not None else 0
        return {"elapsed_s": elapsed, "determined": det, "total": total,
                "accuracy": det, "solved": True, "timed_out": False,
                "error": None}
    if first.startswith("Requires"):
        return {"elapsed_s": elapsed, "determined": 0, "total": total,
                "accuracy": 0, "solved": False, "timed_out": False,
                "error": "Requires additional rules"}
    if first.startswith("Timeout"):
        return {"elapsed_s": elapsed, "determined": 0, "total": total,
                "accuracy": 0, "solved": False, "timed_out": True,
                "error": "internal timeout"}
    return {"elapsed_s": elapsed, "determined": 0, "total": total,
            "accuracy": 0, "solved": False, "timed_out": False,
            "error": f"unexpected stdout: {first[:120]}"}


def make_record(meta: Dict, result: Dict) -> Dict:
    return {
        "level_path": meta["path"],
        "name": meta["name"],
        "author": meta["author"],
        "category": meta["category"],
        "cells": meta.get("cells") or result.get("total"),
        "config": CONFIG_KEY,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "elapsed_s": result.get("elapsed_s"),
        "determined": result.get("determined"),
        "total": result.get("total"),
        "accuracy": result.get("accuracy"),
        "solved": result.get("solved", False),
        "timed_out": result.get("timed_out", False),
        "error": result.get("error"),
        "cycles": [],
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--timeout", type=float, default=60.0)
    p.add_argument("--parallel", type=int, default=4)
    p.add_argument("--no-resume", action="store_true")
    p.add_argument("--levels-dir", default="levels")
    p.add_argument("--runs-file", default="testing/runs.jsonl")
    p.add_argument("--category", choices=["small", "medium", "large"])
    args = p.parse_args()

    levels_dir = os.path.join(_REPO_ROOT, args.levels_dir)
    runs_file = os.path.join(_REPO_ROOT, args.runs_file)
    levels = find_levels(levels_dir, args.category)
    if not levels:
        print(f"No levels found in {levels_dir}")
        sys.exit(1)

    skip: Set[str] = set()
    if not args.no_resume:
        skip = load_done(runs_file, CONFIG_KEY)
        if skip:
            print(f"Resuming: {len(skip)} already done, skipping.")

    todo = [lv for lv in levels if lv["path"] not in skip]
    print(f"Running {len(todo)} levels (parallel={args.parallel}, timeout={args.timeout}s)")

    def task(meta):
        return meta, run_one(meta["abs_path"], args.timeout)

    done = 0
    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        futures = {pool.submit(task, m): m for m in todo}
        for fut in as_completed(futures):
            meta, result = fut.result()
            done += 1
            rec = make_record(meta, result)
            write_record(runs_file, rec)
            tag = ("solved" if result.get("solved")
                   else "TIMEOUT" if result.get("timed_out")
                   else f"unsolved ({result.get('error','?')})")
            cells = (meta.get("cells") or result.get("total") or "?")
            print(f"  [{done}/{len(todo)}] {meta['category']}/{meta['name']} "
                  f"({cells} cells) — {tag} in {result.get('elapsed_s', 0):.3f}s")

    print(f"\nDone. Records appended to {args.runs_file}")


if __name__ == "__main__":
    main()
