"""Exact (one-shot) Hexcells solver using Z3 SMT.

Mirrors `gurobi_exact.py`: all hints added up front, solved with a single
`check()` call. Also exposes `is_unique(problem)` for generation via a
2-call uniqueness check (solve, exclude solution, solve again).
"""

import time
import os
import sys

import z3

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from project.lib.parser import CellType, Modifier, Problem, parse_hexcells


def _b2i(b):
    return z3.If(b, 1, 0)


class Z3ExactSolver:
    def __init__(self, problem: Problem):
        self.problem = problem
        self.solver = z3.Solver()
        self.x = {}
        self._build_model()

    def _build_model(self):
        for c in self.problem.cells:
            self.x[c] = z3.Bool(f"x_{c.q}_{c.r}_{c.s}")

        self.solver.add(
            z3.Sum([_b2i(self.x[c]) for c in self.problem.cells])
            == self.problem.total_mines
        )

        for hint in self.problem.hints:
            scope_vars = [self.x[c] for c in hint.scope if c in self.x]
            self.solver.add(
                z3.Sum([_b2i(v) for v in scope_vars]) == hint.value
            )

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
                    continue

                transitions = [z3.Xor(Y[j - 1], Y[j]) for j in range(len(Y))]
                t_sum = z3.Sum([_b2i(t) for t in transitions])

                if hint.modifier == Modifier.TOGETHER:
                    self.solver.add(t_sum == 2)
                else:
                    self.solver.add(t_sum >= 4)

    def solve(self):
        if self.solver.check() != z3.sat:
            return None
        m = self.solver.model()
        return {c: bool(m.evaluate(self.x[c])) for c in self.problem.cells}

    def is_unique(self) -> bool:
        """Check uniqueness via push/pop: solve, exclude S1, solve again."""
        if self.solver.check() != z3.sat:
            return False

        m = self.solver.model()
        s1 = {c: bool(m.evaluate(self.x[c])) for c in self.problem.cells}

        # Exclusion: at least one cell must differ from s1
        excl = z3.Or([
            self.x[c] != z3.BoolVal(s1[c])
            for c in self.problem.cells
        ])
        self.solver.push()
        self.solver.add(excl)
        unique = self.solver.check() == z3.unsat
        self.solver.pop()
        return unique


def is_unique(problem: Problem) -> bool:
    """Convenience function: build a fresh solver and check uniqueness."""
    return Z3ExactSolver(problem).is_unique()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m utils.z3_exact <level.hexcells>")
        sys.exit(1)

    path = sys.argv[1]
    level = parse_hexcells(path)
    problem = Problem(level)

    solver = Z3ExactSolver(problem)
    start = time.time()
    solution = solver.solve()
    elapsed = time.time() - start

    if solution is None:
        print(f"[{path}] No solution found ({elapsed:.4f}s)")
        sys.exit(1)

    correct = sum(
        1 for c, is_mine in solution.items()
        if is_mine == (c in problem.mines)
    )
    print(f"[{path}] Solved in {elapsed:.4f}s")
    print(f"  Accuracy: {correct}/{len(problem.cells)}")
    print(f"  Unique:   {solver.is_unique()}")
