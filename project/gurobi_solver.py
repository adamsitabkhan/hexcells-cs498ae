"""Gurobi IP module for incremental Hexcells solving.

Exposes the module protocol used by `project.solver`:
  - `step()` runs one force-checking iteration over currently unknown cells
    and returns the list of cells whose value was proven by infeasibility.
    The caller is responsible for applying these reveals to the puzzle state.
  - `on_reveal(coords, is_mine, unlocked_hint)` updates the internal IP model
    to reflect a newly-revealed cell (and adds the unlocked hint, if any).

Also keeps the legacy `solve()` driver so the standalone workflow
(`python -m project.gurobi_solver level.hexcells --viz`) still works.
"""

import time
from typing import List, Tuple

import gurobipy as gp
from gurobipy import GRB

from .lib.parser import CellType, Coords, Hint, Modifier, Problem, parse_hexcells
from .lib.puzzle_state import PuzzleState


class GurobiModule:
    name = "gurobi"

    def __init__(
        self,
        problem: Problem,
        state: PuzzleState = None,
        verbose: bool = False,
        record_frames: bool = False,
    ):
        self.problem = problem
        self.state = state if state is not None else PuzzleState(problem)
        self.verbose = verbose
        self.record_frames = record_frames
        self.frames = []

        self.model = gp.Model("Hexcells_Gurobi")
        self.model.Params.OutputFlag = 0
        self.x = {}
        self._build_initial()

    def _add_xor(self, A, B, W):
        self.model.addConstr(W >= A - B)
        self.model.addConstr(W >= B - A)
        self.model.addConstr(W <= A + B)
        self.model.addConstr(W <= 2 - A - B)

    def _fix_var(self, coords, is_mine: bool):
        v = 1 if is_mine else 0
        self.x[coords].LB = v
        self.x[coords].UB = v

    def _add_hint(self, hint: Hint):
        scope_vars = [self.x[c] for c in hint.scope if c in self.x]
        self.model.addConstr(gp.quicksum(scope_vars) == hint.value)

        if hint.value >= 2 and hint.modifier in (Modifier.TOGETHER, Modifier.SEPARATED):
            Y = []
            if hint.type == CellType.ZONE6:
                for n in hint.coords.neighbors6():
                    Y.append(self.x[n] if n in self.x else 0)
            elif hint.type == CellType.LINE:
                Y.append(0)
                for c in hint.scope:
                    Y.append(self.x[c])
                Y.append(0)
            else:
                return

            W = []
            for j in range(len(Y)):
                A = Y[j - 1]
                B = Y[j]
                w = self.model.addVar(vtype=GRB.BINARY)
                self._add_xor(A, B, w)
                W.append(w)

            if hint.modifier == Modifier.TOGETHER:
                self.model.addConstr(gp.quicksum(W) == 2)
            else:
                self.model.addConstr(gp.quicksum(W) >= 4)

    def _build_initial(self):
        for c in self.problem.cells:
            self.x[c] = self.model.addVar(
                vtype=GRB.BINARY, name=f"x_{c.q}_{c.r}_{c.s}"
            )

        self.model.addConstr(
            gp.quicksum(self.x.values()) == self.problem.total_mines,
            name="total_mines",
        )

        for c, is_mine in self.state.known.items():
            self._fix_var(c, is_mine)

        for hint in self.state.available_hints:
            self._add_hint(hint)

    # ----- Module protocol -----

    def step(self) -> List[Tuple[Coords, bool]]:
        """Run one force-checking iteration. Returns newly forced cells
        without modifying the puzzle state — the caller applies reveals
        and notifies this module via on_reveal()."""
        self.model.optimize()
        if self.model.status != GRB.OPTIMAL:
            return []

        baseline = {c: self.x[c].X > 0.5 for c in self.problem.cells}

        forced = []
        for c in list(self.state.unknown_cells()):
            v = baseline[c]
            orig_lb, orig_ub = self.x[c].LB, self.x[c].UB
            opp = 0 if v else 1
            self.x[c].LB = opp
            self.x[c].UB = opp
            self.model.optimize()
            if self.model.status == GRB.INFEASIBLE:
                forced.append((c, v))
            self.x[c].LB = orig_lb
            self.x[c].UB = orig_ub

        return forced

    def on_reveal(self, coords: Coords, is_mine: bool, unlocked: Hint = None):
        self._fix_var(coords, is_mine)
        if unlocked is not None:
            self._add_hint(unlocked)

    # ----- Legacy standalone driver (preserves viz workflow) -----

    def _snapshot(self, highlighted=None, stuck=None, caption=""):
        if not self.record_frames:
            return
        from .viz.animate import Frame
        self.frames.append(Frame(
            known=dict(self.state.known),
            visible_hint_coords={h.coords for h in self.state.available_hints},
            highlighted=set(highlighted or []),
            stuck=set(stuck or []),
            caption=caption,
        ))

    def solve(self):
        self._snapshot(caption="Initial state — only revealed cells and LINE hints visible")

        iteration = 0
        while not self.state.is_complete():
            iteration += 1
            forced = self.step()

            if self.verbose:
                print(
                    f"  iter {iteration}: revealed {len(forced)} cells "
                    f"({len(self.state.known)}/{len(self.problem.cells)} known)"
                )

            if not forced:
                if self.verbose:
                    print(f"  iter {iteration}: stuck — could not force any cell")
                self._snapshot(
                    stuck=set(self.state.unknown_cells()),
                    caption=f"Stuck at iteration {iteration} — {len(self.state.unknown_cells())} cells undetermined",
                )
                break

            determined_set = {c for c, _ in forced}
            self._snapshot(
                highlighted=determined_set,
                caption=f"Iteration {iteration}: solver determined {len(forced)} cells",
            )

            for c, v in forced:
                unlocked = self.state.reveal(c, v)
                self.on_reveal(c, v, unlocked)

            self._snapshot(
                caption=f"Iteration {iteration}: revealed {len(forced)} cells, new hints unlocked",
            )

        if self.state.is_complete() and self.frames:
            self.frames[-1].caption = f"Puzzle solved in {iteration} iteration(s)"

        return {c: self.state.known.get(c, False) for c in self.problem.cells}


if __name__ == "__main__":
    import os
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m project.gurobi_solver <level.hexcells> [--verbose] [--viz]")
        sys.exit(1)

    path = sys.argv[1]
    flags = sys.argv[2:]
    verbose = "--verbose" in flags
    viz = "--viz" in flags

    level = parse_hexcells(path)
    problem = Problem(level)

    solver = GurobiModule(problem, verbose=verbose, record_frames=viz)
    start = time.time()
    solution = solver.solve()
    elapsed = time.time() - start

    known = len(solver.state.known)
    correct = sum(
        1
        for c, is_mine in solution.items()
        if is_mine == (c in problem.mines)
    )
    print(f"[{path}] Done in {elapsed:.4f}s")
    print(f"  Determined: {known}/{len(problem.cells)} cells")
    print(f"  Accuracy:   {correct}/{len(problem.cells)}")

    if viz:
        from .viz.animate import Animator
        base = os.path.splitext(os.path.basename(path))[0]
        gif_path = os.path.join(os.path.dirname(path) or ".", f"{base}_solve.gif")
        animator = Animator(
            problem, solver.frames,
            title_prefix=f"{base} — ",
            gif_path=gif_path,
        )
        animator.save_gif(gif_path)
        print("Controls: ← / → step  •  Home / End jump  •  Space play/pause  •  s save GIF  •  q quit")
        animator.show()
