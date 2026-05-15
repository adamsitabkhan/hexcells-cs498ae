"""Z3 incremental solver: assumption-literal `step()` on top of the
PbEq-encoded baseline.

This variant overrides only `step()`. After Phase 2 of the Z3 improvements
work the baseline `Z3Module._add_hint` uses `z3.PbEq`, so this class is the
"PbEq + assumption literals" combined variant (Phase 1's `z3_pbeq` plus
`z3_assume` rolled into one).

Phase 1's profile showed the baseline spent 92-97% of wall time in the
per-cell `push / add / check / pop` loop because every `pop` discards the
branch's learned lemmas. Here we instead use `solver.check(p_c)` with one
Boolean indicator literal per cell test:

  - permanently assert `p_c -> (x[c] == not baseline[c])`
  - call `check(p_c)` to test whether forcing the opposite value is unsat
  - never assume `p_c` again

The implication stays in the solver but is dormant; the revealed cell is
then pinned directly by `on_reveal` via the inherited fixing constraint.
Base learned-clause database survives across queries.
"""

from typing import List, Tuple

import z3

from ..lib.parser import Coords, Hint, Problem
from ..lib.puzzle_state import PuzzleState
from ..z3_solver import Z3Module


class Z3AssumeModule(Z3Module):
    name = "z3_assume"

    def step(self) -> List[Tuple[Coords, bool]]:
        if self.solver.check() != z3.sat:
            return []

        m = self.solver.model()
        baseline = {c: bool(m.evaluate(self.x[c])) for c in self.problem.cells}

        forced: List[Tuple[Coords, bool]] = []
        for c in list(self.state.unknown_cells()):
            v = baseline[c]
            p = z3.Bool(f"assume_{c.q}_{c.r}_{c.s}_{1 if v else 0}")
            self.solver.add(z3.Implies(p, self.x[c] == (not v)))
            if self.solver.check(p) == z3.unsat:
                forced.append((c, v))
            # Constraint stays in the solver but is dormant unless p is
            # passed in a future check(). Cell c will be revealed and
            # constrained directly by on_reveal(), making p irrelevant.

        return forced
