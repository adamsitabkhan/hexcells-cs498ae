"""Hexcells level generator with reverse-engineered solvability.

Approach (reverse-engineering, similar to commercial puzzle generators):

  1. **Solved state**: pick a shape and randomly assign mines to cells.
  2. **Clues**: mark every non-mine cell as a ZONE6 numbered cell so that
     revealing it shows the count of adjacent mines.
  3. **Verify**: with ALL non-mines revealed (maximum information), check
     that the puzzle has a unique solution using the exact solver (2 LP/SMT
     calls). This is independent of the incremental solver used for
     benchmarking.
  4. **Refine**: greedily try hiding revealed cells one by one; keep each
     hide only if the puzzle is still uniquely solvable. This shrinks the
     starter clues toward a minimal set, which controls difficulty.

Generation uses the exact solvers (utils/gurobi_exact.py, utils/z3_exact.py)
for fast uniqueness checking. Benchmarking uses the incremental solvers.

Only ZONE6 hints (no LINE, ZONE18, TOGETHER/SEPARATED) are used in v1.

CLI usage:
    venv/bin/python -m utils.generate_level --out /tmp/test.hexcells \\
        [--shape parallelogram|hex] [--size 5] [--mine-density 0.4] \\
        [--minimize] [--min-reveals 1] \\
        [--seed 42] [--max-placements 30] \\
        [--exact-solver gurobi|z3] [--name "..."] [--author "..."]
"""

import argparse
import os
import random
import sys
import time
from typing import Dict, List, Optional, Set, Tuple

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from project.lib.parser import Cell, CellType, Color, Coords, Modifier, Problem


# ---------------------------------------------------------------------------
# Shapes
# ---------------------------------------------------------------------------

def parallelogram(width: int, height: int) -> Set[Coords]:
    return {Coords(q, r, -q - r) for q in range(width) for r in range(height)}


def hex_disk(radius: int) -> Set[Coords]:
    cells = set()
    for q in range(-radius, radius + 1):
        r_lo = max(-radius, -q - radius)
        r_hi = min(radius, -q + radius)
        for r in range(r_lo, r_hi + 1):
            cells.add(Coords(q, r, -q - r))
    return cells


def diamond(width: int, height: int) -> Set[Coords]:
    """Parallelogram in (R, S) axes: R ∈ [0, width), S ∈ [0, height), Q = -R-S.

    Grid properties (odd alignment): i = R-S, j = -R-S.
    Both i_span and j_span equal width+height-2, so up to diamond(17,17)=289
    cells fit in the 33×33 grid.
    """
    cells = set()
    for ri in range(width):
        for si in range(height):
            cells.add(Coords(-ri - si, ri, si))
    return cells


def filled_rect(i_span: int, j_span: int) -> Set[Coords]:
    """All valid hex positions in a grid rectangle.

    Fills every (i, j) with 0 ≤ i ≤ i_span, 0 ≤ j ≤ j_span, (i+j) even.
    Converts to axial coords via: q=j, r=(i-j)/2, s=-(i+j)/2.
    Enables cell counts up to ~400 with i_span, j_span ≤ 32.
    """
    cells = set()
    for i in range(i_span + 1):
        for j in range(j_span + 1):
            if (i + j) % 2 == 0:
                q = j
                r = (i - j) // 2
                cells.add(Coords(q, r, -q - r))
    return cells


def build_shape(shape: str, size: int,
                width: int = None, height: int = None,
                i_span: int = None, j_span: int = None) -> Set[Coords]:
    if shape == "parallelogram":
        return parallelogram(size, size)
    if shape == "hex":
        return hex_disk(size)
    if shape == "diamond":
        w = width or size
        h = height or size
        return diamond(w, h)
    if shape == "filled_rect":
        return filled_rect(i_span, j_span)
    raise ValueError(f"Unknown shape: {shape}")


# ---------------------------------------------------------------------------
# Grid placement (33×33, parser's odd alignment: i+j even)
# ---------------------------------------------------------------------------

GRID_SIZE = 33


def axial_to_grid(c: Coords) -> Tuple[int, int]:
    return 2 * c.r + c.q, c.q


def shift_to_grid(cells: Set[Coords]) -> Optional[Dict[Coords, Tuple[int, int]]]:
    raw = {c: axial_to_grid(c) for c in cells}
    is_, js = zip(*raw.values())
    i_min, i_max = min(is_), max(is_)
    j_min, j_max = min(js), max(js)
    i_span = i_max - i_min
    j_span = j_max - j_min
    if i_span >= GRID_SIZE or j_span >= GRID_SIZE:
        return None

    i_off = (GRID_SIZE - 1 - i_span) // 2 - i_min
    j_off = (GRID_SIZE - 1 - j_span) // 2 - j_min
    if (i_off + j_off) % 2 != 0:
        if j_off + 1 + j_max < GRID_SIZE:
            j_off += 1
        else:
            i_off += 1

    placed = {c: (i + i_off, j + j_off) for c, (i, j) in raw.items()}
    for i, j in placed.values():
        if not (0 <= i < GRID_SIZE and 0 <= j < GRID_SIZE):
            return None
        if (i + j) % 2 != 0:
            return None
    return placed


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------

def write_hexcells(
    name: str,
    author: str,
    cell_grid_pos: Dict[Coords, Tuple[int, int]],
    mines: Set[Coords],
    revealed: Set[Coords],
    path: str,
):
    grid = [['.'] * (2 * GRID_SIZE) for _ in range(GRID_SIZE)]
    for c, (i, j) in cell_grid_pos.items():
        col = 2 * j
        if c in mines:
            grid[i][col] = 'X' if c in revealed else 'x'
            grid[i][col + 1] = '.'
        else:
            grid[i][col] = 'O' if c in revealed else 'o'
            grid[i][col + 1] = '+'

    lines = ["Hexcells level v1", name, author, "", ""]
    lines.extend(''.join(row) for row in grid)

    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, 'w') as f:
        f.write('\n'.join(lines) + '\n')


def build_problem(
    cells: Set[Coords],
    mines: Set[Coords],
    revealed: Set[Coords],
) -> Problem:
    """Construct a Problem directly in memory — no file I/O needed."""
    level = {}
    for c in cells:
        is_mine = c in mines
        is_revealed = c in revealed
        color = Color.BLUE if is_mine else Color.BLACK
        if is_revealed and not is_mine:
            cell_type = CellType.ZONE6
        else:
            cell_type = CellType.ZONE0
        level[c] = Cell(
            type=cell_type,
            revealed=is_revealed,
            color=color,
            modifier=Modifier.ANYWHERE if (is_revealed and not is_mine) else None,
        )
    return Problem(level)


# ---------------------------------------------------------------------------
# Uniqueness check using exact solvers (no incremental solver dependency)
# ---------------------------------------------------------------------------

def _load_exact(solver_name: str):
    if solver_name == "gurobi":
        from utils.gurobi_exact import GurobiExactSolver
        return GurobiExactSolver
    if solver_name == "z3":
        from utils.z3_exact import Z3ExactSolver
        return Z3ExactSolver
    raise ValueError(f"Unknown exact solver: {solver_name}")


def check_unique(
    cells: Set[Coords],
    mines: Set[Coords],
    revealed: Set[Coords],
    exact_solver: str,
) -> bool:
    """Build the problem in memory and check uniqueness via 2 solver calls."""
    problem = build_problem(cells, mines, revealed)
    solver_cls = _load_exact(exact_solver)
    return solver_cls(problem).is_unique()


# ---------------------------------------------------------------------------
# Generation pipeline
# ---------------------------------------------------------------------------

def generate(
    shape: str = "parallelogram",
    size: int = 5,
    width: int = None,
    height: int = None,
    i_span: int = None,
    j_span: int = None,
    mine_density: float = 0.4,
    minimize: bool = True,
    min_reveals: int = 1,
    seed: Optional[int] = None,
    max_placements: int = 30,
    exact_solver: str = "gurobi",
    name: str = "Generated",
    author: str = "generator",
    out_path: str = "/tmp/generated.hexcells",
    verbose: bool = False,
) -> dict:
    """Generate one uniquely-solvable level via reverse-engineering + minimization.

    Uses the exact solver (2 LP/SMT calls) for uniqueness checks during
    generation. The incremental solver is not involved here.

    Returns a metadata dict with generation stats.
    """
    rng = random.Random(seed)
    cells = build_shape(shape, size, width=width, height=height,
                        i_span=i_span, j_span=j_span)
    placed = shift_to_grid(cells)
    if placed is None:
        raise ValueError(f"Shape {shape}({size}) doesn't fit a {GRID_SIZE}×{GRID_SIZE} grid")

    cells_list = sorted(cells)
    n_total = len(cells_list)
    n_mines = max(1, min(n_total - 1, round(n_total * mine_density)))

    t0 = time.time()

    for placement in range(1, max_placements + 1):
        # Step 1: random mine placement
        shuffled = cells_list[:]
        rng.shuffle(shuffled)
        mines = set(shuffled[:n_mines])
        non_mines = [c for c in cells_list if c not in mines]

        # Step 2+3: all non-mines revealed; verify unique solution exists
        revealed = set(non_mines)
        try:
            unique = check_unique(cells, mines, revealed, exact_solver)
        except Exception as e:
            if verbose:
                print(f"  placement {placement}: solver error {e}")
            continue

        if not unique:
            if verbose:
                print(f"  placement {placement}: ambiguous with full reveals")
            continue

        if verbose:
            print(f"  placement {placement}: unique with {len(revealed)} reveals")

        if not minimize:
            write_hexcells(name, author, placed, mines, revealed, out_path)
            elapsed = time.time() - t0
            return _result_dict(shape, size, n_total, n_mines, len(revealed),
                                placement, elapsed, out_path)

        # Step 4: greedily hide cells while keeping unique solvability
        candidates = list(revealed)
        rng.shuffle(candidates)
        hidden_count = 0
        for c in candidates:
            if len(revealed) <= min_reveals:
                break
            revealed.discard(c)
            try:
                ok = check_unique(cells, mines, revealed, exact_solver)
            except Exception:
                ok = False
            if not ok:
                revealed.add(c)
            else:
                hidden_count += 1

        write_hexcells(name, author, placed, mines, revealed, out_path)
        elapsed = time.time() - t0
        if verbose:
            print(f"  minimized: {len(revealed)} reveals (hid {hidden_count})")
        return _result_dict(shape, size, n_total, n_mines, len(revealed),
                            placement, elapsed, out_path)

    raise RuntimeError(
        f"No uniquely-solvable mine placement after {max_placements} tries. "
        f"Try a different size or mine density."
    )


def _result_dict(shape, size, total, n_mines, n_reveals, placements,
                 elapsed, out_path):
    return {
        "shape": shape,
        "size": size,
        "cells": total,
        "mines": n_mines,
        "revealed_start": n_reveals,
        "placements_tried": placements,
        "elapsed_s": elapsed,
        "out_path": out_path,
    }


def main():
    p = argparse.ArgumentParser(
        prog="python -m utils.generate_level",
        description="Generate a uniquely-solvable Hexcells level via reverse engineering.",
    )
    p.add_argument("--out", required=True, help="Output .hexcells path.")
    p.add_argument("--shape", choices=["parallelogram", "hex"], default="parallelogram")
    p.add_argument("--size", type=int, default=5)
    p.add_argument("--mine-density", type=float, default=0.4)
    p.add_argument("--minimize", action="store_true",
                   help="Greedily minimize starter clues (harder puzzles).")
    p.add_argument("--min-reveals", type=int, default=1,
                   help="Don't drop below this many revealed cells during minimization.")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--max-placements", type=int, default=30)
    p.add_argument("--exact-solver", choices=["gurobi", "z3"], default="gurobi",
                   help="Exact solver used for uniqueness checking during generation.")
    p.add_argument("--name", default="Generated")
    p.add_argument("--author", default="generator")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    meta = generate(
        shape=args.shape, size=args.size,
        mine_density=args.mine_density,
        minimize=args.minimize, min_reveals=args.min_reveals,
        seed=args.seed, max_placements=args.max_placements,
        exact_solver=args.exact_solver,
        name=args.name, author=args.author,
        out_path=args.out, verbose=args.verbose,
    )
    print(f"Generated: {meta['out_path']}")
    print(f"  shape={meta['shape']}({meta['size']})  cells={meta['cells']}  "
          f"mines={meta['mines']}  revealed={meta['revealed_start']}  "
          f"placements={meta['placements_tried']}  elapsed={meta['elapsed_s']:.2f}s")


if __name__ == "__main__":
    main()
