"""Z3 SMT module for incremental Hexcells solving.

Mirrors `gurobi_solver.py` but uses Z3's `push`/`pop` to test alternative
assignments without permanently extending the solver state.

Module protocol:
  - `step()` runs one force-checking iteration and returns newly forced cells
    (without modifying the puzzle state).
  - `on_reveal(coords, is_mine, unlocked_hint)` adds the corresponding
    equality / hint constraint to the solver.
"""

import time
from typing import List, Tuple

import z3

from .lib.parser import CellType, Coords, Hint, Modifier, Problem, parse_hexcells
from .lib.puzzle_state import PuzzleState


class Z3Module:
    name = "z3"

    def __init__(self, problem: Problem, state: PuzzleState = None, verbose: bool = False):
        self.problem = problem
        self.state = state if state is not None else PuzzleState(problem)
        self.verbose = verbose

        self.solver = z3.Solver()
        self.x = {}
        self._build_initial()

    def _add_hint(self, hint: Hint):
        scope_vars = [self.x[c] for c in hint.scope if c in self.x]
        if scope_vars:
            self.solver.add(z3.PbEq([(v, 1) for v in scope_vars], hint.value))

        if hint.value >= 2 and hint.modifier in (
            Modifier.TOGETHER,
            Modifier.SEPARATED,
        ):
            Y = []
            if hint.type == CellType.ZONE6:
                for n in hint.coords.neighbors6():
                    Y.append(self.x[n] if n in self.x else z3.BoolVal(False))
            elif hint.type == CellType.LINE:
                Y.append(z3.BoolVal(False))
                for c in hint.scope:
                    Y.append(self.x[c])
                Y.append(z3.BoolVal(False))
            else:
                return

            transitions = []
            for j in range(len(Y)):
                t = z3.Bool(f"t_{hint.coords.q}_{hint.coords.r}_{hint.coords.s}_{j}")
                self.solver.add(t == z3.Xor(Y[j - 1], Y[j]))
                transitions.append(t)

            if hint.modifier == Modifier.TOGETHER:
                self.solver.add(z3.PbEq([(t, 1) for t in transitions], 2))
            else:
                self.solver.add(z3.PbGe([(t, 1) for t in transitions], 4))

    def _build_initial(self):
        for c in self.problem.cells:
            self.x[c] = z3.Bool(f"x_{c.q}_{c.r}_{c.s}")

        self.solver.add(
            z3.PbEq([(self.x[c], 1) for c in self.problem.cells],
                    self.problem.total_mines)
        )

        for c, is_mine in self.state.known.items():
            self.solver.add(self.x[c] == is_mine)

        for hint in self.state.available_hints:
            self._add_hint(hint)

    # ----- Module protocol -----

    def step(self) -> List[Tuple[Coords, bool]]:
        if self.solver.check() != z3.sat:
            return []

        m = self.solver.model()
        baseline = {c: bool(m.evaluate(self.x[c])) for c in self.problem.cells}

        forced = []
        for c in list(self.state.unknown_cells()):
            v = baseline[c]
            self.solver.push()
            self.solver.add(self.x[c] == (not v))
            result = self.solver.check()
            self.solver.pop()
            if result == z3.unsat:
                forced.append((c, v))

        return forced

    def on_reveal(self, coords: Coords, is_mine: bool, unlocked: Hint = None):
        self.solver.add(self.x[coords] == is_mine)
        if unlocked is not None:
            self._add_hint(unlocked)

    # ----- Legacy standalone driver -----

    def solve(self):
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
                break

            for c, v in forced:
                unlocked = self.state.reveal(c, v)
                self.on_reveal(c, v, unlocked)

        return {c: self.state.known.get(c, False) for c in self.problem.cells}


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m project.z3_solver <level.hexcells> [--verbose]")
        sys.exit(1)

    path = sys.argv[1]
    verbose = "--verbose" in sys.argv[2:]

    level = parse_hexcells(path)
    problem = Problem(level)

    solver = Z3Module(problem, verbose=verbose)
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
