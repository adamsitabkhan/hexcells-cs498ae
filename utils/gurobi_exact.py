"""Exact (one-shot) Hexcells solver using Gurobi IP.

Builds the full model with all hints up front and solves once.
Also exposes `is_unique(problem)` for generation — a 2-call uniqueness
check that is much cheaper than the incremental force-checking approach.
"""

import time

import gurobipy as gp
from gurobipy import GRB

import os
import sys
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from project.lib.parser import CellType, Modifier, Problem, parse_hexcells


class GurobiExactSolver:
    def __init__(self, problem: Problem):
        self.problem = problem
        self.model = gp.Model("Hexcells_Exact")
        self.model.Params.OutputFlag = 0
        self.x = {}
        self._build_model()

    def _add_xor(self, A, B, W):
        self.model.addConstr(W >= A - B)
        self.model.addConstr(W >= B - A)
        self.model.addConstr(W <= A + B)
        self.model.addConstr(W <= 2 - A - B)

    def _build_model(self):
        for c in self.problem.cells:
            self.x[c] = self.model.addVar(
                vtype=GRB.BINARY, name=f"x_{c.q}_{c.r}_{c.s}"
            )

        self.model.addConstr(
            gp.quicksum(self.x.values()) == self.problem.total_mines,
            name="total_mines",
        )

        for i, hint in enumerate(self.problem.hints):
            scope_vars = [self.x[c] for c in hint.scope if c in self.x]
            self.model.addConstr(
                gp.quicksum(scope_vars) == hint.value, name=f"hint_{i}"
            )

            if hint.value >= 2 and hint.modifier in (
                Modifier.TOGETHER,
                Modifier.SEPARATED,
            ):
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
                    continue

                W = []
                for j in range(len(Y)):
                    A = Y[j - 1]
                    B = Y[j]
                    w = self.model.addVar(vtype=GRB.BINARY, name=f"w_{i}_{j}")
                    self._add_xor(A, B, w)
                    W.append(w)

                if hint.modifier == Modifier.TOGETHER:
                    self.model.addConstr(gp.quicksum(W) == 2, name=f"together_{i}")
                else:
                    self.model.addConstr(gp.quicksum(W) >= 4, name=f"separated_{i}")

    def solve(self):
        self.model.optimize()
        if self.model.status == GRB.OPTIMAL:
            return {c: self.x[c].X > 0.5 for c in self.problem.cells}
        return None

    def is_unique(self) -> bool:
        """Check that exactly one solution exists via a 2-call approach.

        Solve once to get S1, then add an exclusion constraint and solve
        again. If the second solve is infeasible, the solution is unique.
        """
        self.model.optimize()
        if self.model.status != GRB.OPTIMAL:
            return False

        s1 = {c: self.x[c].X > 0.5 for c in self.problem.cells}

        # Exclusion constraint: solution must differ from s1 in at least one cell
        excl = self.model.addConstr(
            gp.quicksum(
                self.x[c] if not s1[c] else (1 - self.x[c])
                for c in self.problem.cells
            ) >= 1,
            name="_excl",
        )
        self.model.optimize()
        unique = self.model.status == GRB.INFEASIBLE
        self.model.remove(excl)
        return unique


def is_unique(problem: Problem) -> bool:
    """Convenience function: build a fresh solver and check uniqueness."""
    return GurobiExactSolver(problem).is_unique()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m utils.gurobi_exact <level.hexcells>")
        sys.exit(1)

    path = sys.argv[1]
    level = parse_hexcells(path)
    problem = Problem(level)

    solver = GurobiExactSolver(problem)
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
