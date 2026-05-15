"""Batch level generator — produces a diverse set of generated levels.

Sweeps shape × size × mine_density × seed and writes each level to
`levels/generated/<descriptive-slug>/level.hexcells`. Also writes an
`index.jsonl` summary with per-level generation stats.

Difficulty is controlled implicitly by:
  - shape and size (more cells → typically harder)
  - mine density (denser → more constraints, often harder)
  - minimization (always on here, so puzzles are near-minimal)

Run:
    venv/bin/python -m utils.generate_batch [--out-root levels/generated] \\
        [--solver gurobi|z3] [--time-budget 600]
"""

import argparse
import json
import os
import sys
import time
from typing import List

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from utils.generate_level import generate


def build_configs() -> List[dict]:
    """Sweep of generation parameters covering small/medium/large + easy/med/hard."""
    configs = []

    # Small puzzles — fast, mostly easy
    for shape in ["parallelogram", "hex"]:
        for size in ([3, 4] if shape == "parallelogram" else [2, 3]):
            for md in [0.30, 0.40, 0.50]:
                for seed in range(1, 6):
                    configs.append({
                        "shape": shape, "size": size,
                        "mine_density": md, "seed": seed,
                    })

    # Medium puzzles
    for shape in ["parallelogram", "hex"]:
        for size in ([5, 6] if shape == "parallelogram" else [4]):
            for md in [0.30, 0.40, 0.50]:
                for seed in range(1, 6):
                    configs.append({
                        "shape": shape, "size": size,
                        "mine_density": md, "seed": seed,
                    })

    # Larger puzzles (fewer seeds — each takes longer)
    for shape in ["parallelogram", "hex"]:
        for size in ([7] if shape == "parallelogram" else [5]):
            for md in [0.35, 0.45]:
                for seed in range(1, 4):
                    configs.append({
                        "shape": shape, "size": size,
                        "mine_density": md, "seed": seed,
                    })

    return configs


def build_large_configs() -> List[dict]:
    """Configs targeting 50–400 cells using diamond and filled_rect shapes.

    Minimization is applied for levels ≤200 cells; disabled for larger ones
    (each uniqueness check on a 300+ cell model takes longer, and levels with
    all non-mines revealed are still valid uniquely-solvable test inputs).
    """
    configs = []

    # --- hex disk: 61–217 cells, with minimization ---
    for radius, seeds in [(4, 3), (5, 3), (6, 2), (7, 2), (8, 2)]:
        for md in [0.35, 0.45]:
            for seed in range(1, seeds + 1):
                configs.append({
                    "shape": "hex", "size": radius,
                    "mine_density": md, "seed": seed, "minimize": True,
                })

    # --- diamond: 64–289 cells ---
    for (w, h), seeds, minimize in [
        ((8, 8),   3, True),   # 64 cells
        ((10, 10), 3, True),   # 100 cells
        ((12, 12), 2, True),   # 144 cells
        ((14, 14), 2, True),   # 196 cells
        ((16, 16), 2, False),  # 256 cells — skip minimization
        ((17, 17), 2, False),  # 289 cells
    ]:
        for md in [0.35, 0.45]:
            for seed in range(1, seeds + 1):
                configs.append({
                    "shape": "diamond", "width": w, "height": h,
                    "mine_density": md, "seed": seed, "minimize": minimize,
                })

    # --- filled_rect: 221–392 cells, no minimization ---
    # Note: 0.45 density fails for filled_rect (symmetric grids → ambiguous).
    # Use 0.30 and 0.35 only; add extra seeds to cover the 50-level target.
    for (isp, jsp), seeds in [
        ((20, 20), 3),   # 221 cells
        ((22, 22), 3),   # 265 cells
        ((24, 24), 3),   # 313 cells
        ((26, 24), 2),   # 338 cells
        ((28, 24), 2),   # 363 cells
        ((28, 26), 2),   # 392 cells
    ]:
        for md in [0.30, 0.35]:
            for seed in range(1, seeds + 1):
                configs.append({
                    "shape": "filled_rect", "i_span": isp, "j_span": jsp,
                    "mine_density": md, "seed": seed, "minimize": False,
                })

    return configs


def slug_for(cfg: dict, meta: dict) -> str:
    """Descriptive directory name encoding generation params + result."""
    md_pct = int(round(cfg["mine_density"] * 100))
    shape = cfg["shape"]
    if shape == "diamond":
        dim = f"w{cfg['width']}h{cfg['height']}"
    elif shape == "filled_rect":
        dim = f"i{cfg['i_span']}j{cfg['j_span']}"
    else:
        dim = f"s{cfg.get('size', '?')}"
    return (
        f"{shape[:3]}_{dim}"
        f"_md{md_pct}"
        f"_c{meta['cells']}"
        f"_r{meta['revealed_start']}"
        f"_seed{cfg['seed']}"
    )


def main():
    p = argparse.ArgumentParser(
        prog="python -m utils.generate_batch",
        description="Generate a diverse batch of Hexcells levels.",
    )
    p.add_argument("--out-root", default="levels/generated",
                   help="Output directory under repo root.")
    p.add_argument("--exact-solver", choices=["gurobi", "z3"], default="gurobi",
                   help="Exact solver used for uniqueness checking during generation.")
    p.add_argument("--time-budget", type=float, default=600.0,
                   help="Stop generation after this many seconds (default 600).")
    p.add_argument("--max-placements", type=int, default=30)
    p.add_argument("--min-reveals", type=int, default=1)
    p.add_argument("--large", action="store_true",
                   help="Generate the 50–400 cell batch (diamond + filled_rect shapes).")
    p.add_argument("--skip-existing", action="store_true",
                   help="Skip configs whose output directory already exists.")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    out_root = os.path.join(_REPO_ROOT, args.out_root)
    os.makedirs(out_root, exist_ok=True)
    index_path = os.path.join(out_root, "index.jsonl")

    configs = build_large_configs() if args.large else build_configs()
    print(f"Planned {len(configs)} levels. Output: {out_root}")
    print(f"Time budget: {args.time_budget:.0f}s")

    successes = 0
    failures = 0
    skipped = 0
    t_start = time.time()

    # Open in append mode so reruns add to the index
    with open(index_path, "a") as idx_f:
        for i, cfg in enumerate(configs, 1):
            elapsed_total = time.time() - t_start
            if elapsed_total > args.time_budget:
                print(f"[budget] Stopping after {elapsed_total:.0f}s "
                      f"({i-1}/{len(configs)} processed)")
                break

            # Provisional path (slug depends on result; use a temp name first)
            tmp_path = os.path.join(out_root, ".tmp_generated.hexcells")
            try:
                meta = generate(
                    shape=cfg["shape"],
                    size=cfg.get("size", 1),
                    width=cfg.get("width"),
                    height=cfg.get("height"),
                    i_span=cfg.get("i_span"),
                    j_span=cfg.get("j_span"),
                    mine_density=cfg["mine_density"],
                    minimize=cfg.get("minimize", True),
                    min_reveals=args.min_reveals,
                    seed=cfg["seed"], max_placements=args.max_placements,
                    exact_solver=args.exact_solver,
                    name=f"Generated {cfg['shape']}",
                    author="generator",
                    out_path=tmp_path, verbose=False,
                )
            except Exception as e:
                failures += 1
                print(f"[{i:3d}/{len(configs)}] FAIL {cfg}: {e}")
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                continue

            slug = slug_for(cfg, meta)
            level_dir = os.path.join(out_root, slug)
            level_path = os.path.join(level_dir, "level.hexcells")

            if os.path.exists(level_path) and args.skip_existing:
                os.remove(tmp_path)
                skipped += 1
                continue

            os.makedirs(level_dir, exist_ok=True)
            os.replace(tmp_path, level_path)

            record = {
                "slug": slug,
                "level_path": os.path.relpath(level_path, _REPO_ROOT),
                "shape": cfg["shape"],
                "size": cfg.get("size"),
                "width": cfg.get("width"),
                "height": cfg.get("height"),
                "i_span": cfg.get("i_span"),
                "j_span": cfg.get("j_span"),
                "mine_density": cfg["mine_density"],
                "seed": cfg["seed"],
                "cells": meta["cells"],
                "mines": meta["mines"],
                "revealed_start": meta["revealed_start"],
                "placements_tried": meta["placements_tried"],
                "elapsed_gen_s": meta["elapsed_s"],
            }
            idx_f.write(json.dumps(record) + "\n")
            idx_f.flush()

            successes += 1
            if args.verbose or i % 10 == 0:
                print(
                    f"[{i:3d}/{len(configs)}] {slug}  "
                    f"cells={meta['cells']} reveals={meta['revealed_start']} "
                    f"({meta['elapsed_s']:.2f}s)"
                )

    elapsed = time.time() - t_start
    print(f"\nDone in {elapsed:.1f}s. "
          f"successes={successes}  failures={failures}  skipped={skipped}")
    print(f"Index: {index_path}")


if __name__ == "__main__":
    main()
