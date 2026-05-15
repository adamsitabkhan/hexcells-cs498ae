"""Modular Hexcells solver — composes heuristics and a full solver.

Each *cycle*:
  1. Heuristic phase: run all selected heuristics in a loop until none of
     them can force any new cell (fixpoint).
  2. Solver phase: run the selected full solver (Gurobi or Z3) for up to
     M force-checking iterations, stopping early if a step forces nothing.

Cycles repeat until either the puzzle is fully determined or an entire
cycle makes no progress.

CLI usage:
    python -m project.solve <level.hexcells> \\
        [--heuristics pspr,ac3] [--solver gurobi|z3] [-M 100] [-v]
        [--viz] [--gif PATH]

The `--heuristics` list is order-sensitive — heuristics are tried in the
given order within each fixpoint pass. The `--solver` argument is optional;
omit it for a pure-heuristic run.
"""

import argparse
import os
import time
from typing import List, Optional, Tuple

from .lib.parser import Coords, Problem, parse_hexcells
from .lib.puzzle_state import PuzzleState
from .heuristics import AC3, PSPR


HEURISTIC_REGISTRY = {
    "pspr": PSPR,
    "ac3": AC3,
}


def _load_solver(name):
    if name is None:
        return None
    if name == "gurobi":
        from .gurobi_solver import GurobiModule
        return GurobiModule
    if name == "z3":
        from .z3_solver import Z3Module
        return Z3Module
    if name == "z3_assume":
        from .experiments.z3_assumptions import Z3AssumeModule
        return Z3AssumeModule
    if name == "z3_qffd":
        from .experiments.z3_qffd import Z3QffdModule
        return Z3QffdModule
    raise ValueError(f"Unknown solver: {name}")


def _apply_reveals(state: PuzzleState, modules, reveals: List[Tuple[Coords, bool]]) -> int:
    """Commit reveals to the puzzle state and notify all modules.
    Returns the number of cells actually newly revealed (skips duplicates).
    """
    n = 0
    for c, is_mine in reveals:
        if c in state.known:
            continue
        unlocked = state.reveal(c, is_mine)
        for m in modules:
            m.on_reveal(c, is_mine, unlocked)
        n += 1
    return n


def run(
    problem: Problem,
    heuristic_names: List[str],
    solver_name: Optional[str],
    M: int,
    verbose: bool = False,
    frames: Optional[list] = None,
    stats: Optional[list] = None,
) -> PuzzleState:
    state = PuzzleState(problem)
    total = len(problem.cells)

    heuristics = [HEURISTIC_REGISTRY[h](problem, state) for h in heuristic_names]
    solver_cls = _load_solver(solver_name)
    solver = solver_cls(problem, state=state, verbose=verbose) if solver_cls else None
    all_modules = heuristics + ([solver] if solver else [])

    def snapshot(heuristic_hl=None, solver_hl=None, stuck=None, caption=""):
        if frames is None:
            return
        from .viz.animate import Frame
        frames.append(Frame(
            known=dict(state.known),
            visible_hint_coords={h.coords for h in state.available_hints},
            highlighted=set(solver_hl or []),
            heuristic_highlighted=set(heuristic_hl or []),
            stuck=set(stuck or []),
            caption=caption,
        ))

    def new_cells(reveals):
        """Filter a reveals list to cells not yet in state.known."""
        return [(c, v) for c, v in reveals if c not in state.known]

    snapshot(caption="Initial state — revealed cells and LINE hints")

    cycle = 0
    while not state.is_complete():
        cycle += 1
        before = len(state.known)

        # --- Phase 1: heuristics to fixpoint ---
        h_forced_total = 0
        while True:
            any_progress = False
            for h in heuristics:
                forced = h.step()
                if not forced:
                    continue
                new = new_cells(forced)
                if not new:
                    continue
                new_set = {c for c, _ in new}
                snapshot(
                    heuristic_hl=new_set,
                    caption=f"{h.name.upper()}: {len(new)} cells — cycle {cycle}",
                )
                n = _apply_reveals(state, all_modules, forced)
                snapshot(
                    caption=f"After {h.name.upper()} — {len(state.known)}/{total} known",
                )
                if n > 0:
                    any_progress = True
                    h_forced_total += n
                    if stats is not None:
                        stats.append({
                            "phase": "heuristic", "module": h.name,
                            "cycle": cycle, "cells_forced": n,
                            "known_after": len(state.known),
                        })
            if not any_progress:
                break

        if verbose and heuristics and h_forced_total:
            print(f"  cycle {cycle}: heuristics forced {h_forced_total} cells "
                  f"({len(state.known)}/{total} known)")

        if state.is_complete():
            break

        # --- Phase 2: solver for up to M iterations ---
        if solver is not None:
            for it in range(1, M + 1):
                if state.is_complete():
                    break
                forced = solver.step()
                if not forced:
                    if verbose:
                        print(f"  cycle {cycle}: solver iter {it} stuck")
                    break
                new = new_cells(forced)
                if new:
                    new_set = {c for c, _ in new}
                    snapshot(
                        solver_hl=new_set,
                        caption=f"{solver.name.upper()} iter {it}: {len(new)} cells — cycle {cycle}",
                    )
                n = _apply_reveals(state, all_modules, forced)
                if n > 0:
                    snapshot(
                        caption=f"After {solver.name.upper()} iter {it} — "
                                f"{len(state.known)}/{total} known",
                    )
                    if stats is not None:
                        stats.append({
                            "phase": "solver", "module": solver.name,
                            "cycle": cycle, "iteration": it,
                            "cells_forced": n, "known_after": len(state.known),
                        })
                if verbose:
                    print(f"  cycle {cycle}: solver iter {it} forced {n} cells "
                          f"({len(state.known)}/{total} known)")

        if len(state.known) == before:
            if verbose:
                print(f"  cycle {cycle}: no progress, stopping")
            break

    # Final frame
    if state.is_complete():
        snapshot(caption=f"Solved! All {total} cells determined.")
    else:
        unknown = state.unknown_cells()
        snapshot(
            stuck=unknown,
            caption=f"Stuck — {len(state.known)}/{total} determined, "
                    f"{len(unknown)} undetermined",
        )

    return state


def main():
    p = argparse.ArgumentParser(
        prog="python -m project.solve",
        description="Modular Hexcells solver (heuristics + optional full solver).",
    )
    p.add_argument("path", help="Path to a .hexcells level file")
    p.add_argument(
        "--heuristics", default="",
        help="Comma-separated list of heuristics, in order (choices: pspr, ac3). "
             "Empty = no heuristics.",
    )
    p.add_argument(
        "--solver", default=None,
        choices=["gurobi", "z3", "z3_assume", "z3_qffd"],
        help="Optional full solver to run between heuristic fixpoints.",
    )
    p.add_argument(
        "-M", "--iterations", type=int, default=100,
        help="Max solver iterations per cycle (default 100).",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--viz", action="store_true",
                   help="Show interactive step-by-step animation after solving.")
    p.add_argument("--gif", metavar="PATH",
                   help="Save animation as GIF to PATH (implies frame recording).")
    args = p.parse_args()

    heuristic_names = [s.strip().lower() for s in args.heuristics.split(",") if s.strip()]
    for h in heuristic_names:
        if h not in HEURISTIC_REGISTRY:
            p.error(f"Unknown heuristic: {h!r}. Choices: {sorted(HEURISTIC_REGISTRY)}")

    if not heuristic_names and not args.solver:
        p.error("Must select at least one heuristic (--heuristics) or a solver (--solver).")

    level = parse_hexcells(args.path)
    problem = Problem(level)

    pieces = heuristic_names + ([args.solver] if args.solver else [])
    print(f"[{args.path}] modules: {' → '.join(pieces)}  M={args.iterations}")

    frames = [] if (args.viz or args.gif) else None

    start = time.time()
    state = run(problem, heuristic_names, args.solver, args.iterations,
                verbose=args.verbose, frames=frames)
    elapsed = time.time() - start

    known = len(state.known)
    correct = sum(
        1 for c, is_mine in state.known.items()
        if is_mine == (c in problem.mines)
    )
    print(f"  Time:       {elapsed:.4f}s")
    print(f"  Determined: {known}/{len(problem.cells)} cells")
    print(f"  Accuracy:   {correct}/{known if known else 1} of determined")

    if frames:
        from .viz.animate import Animator
        base = os.path.splitext(os.path.basename(args.path))[0]
        gif_path = args.gif or os.path.join(
            os.path.dirname(args.path) or ".", f"{base}_solve.gif"
        )
        animator = Animator(problem, frames, title_prefix=f"{base} — ", gif_path=gif_path)
        if args.gif:
            animator.save_gif(gif_path)
        if args.viz:
            print(f"  Frames: {len(frames)}  "
                  "  ← / → step  •  Home / End jump  •  Space play/pause  "
                  "•  s save GIF  •  q quit")
            animator.show()


if __name__ == "__main__":
    main()
