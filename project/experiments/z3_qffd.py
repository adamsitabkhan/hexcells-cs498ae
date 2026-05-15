"""Z3 incremental solver: QF_FD finite-domain solver on top of the
PbEq-encoded baseline.

After Phase 2 of the Z3 improvements work the baseline `Z3Module` already
uses `z3.PbEq` for cardinality, so this variant tests whether stacking the
QF_FD finite-domain solver on top of that encoding yields a further win
(or a regression on large levels, as Phase 1's results suggested).

Per the Z3 docs, `SolverFor("QF_FD")` selects a SAT-based solver with
native cardinality and pseudo-Boolean constraint propagation. We bypass
the parent's `__init__` so we can swap the solver before `_build_initial`
asserts anything into it.
"""

import z3

from ..z3_solver import Z3Module


class Z3QffdModule(Z3Module):
    name = "z3_qffd"

    def __init__(self, problem, **kwargs):
        # Bypass parent's __init__ so we can swap the solver before
        # _build_initial() asserts anything into it.
        self.problem = problem
        self.state = kwargs.get("state")
        if self.state is None:
            from ..lib.puzzle_state import PuzzleState
            self.state = PuzzleState(problem)
        self.verbose = kwargs.get("verbose", False)

        self.solver = z3.SolverFor("QF_FD")
        self.x = {}
        self._build_initial()
