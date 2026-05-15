"""Heuristic propagation modules for incremental Hexcells solving.

Each module exposes the same protocol as the full IP / SMT modules:
  - `step()` runs one pass and returns newly forced (Coords, is_mine) cells.
  - `on_reveal(coords, is_mine, unlocked)` is a no-op because heuristics
    read the puzzle state fresh on every call.

The orchestrator (see `project.solve`) loops heuristic `step()` calls
until none of them produce new reveals — i.e. heuristic propagation runs
to fixpoint before any expensive solver call.

Note: these heuristics enforce only the count constraint on each hint
(`sum(scope) = value`). The TOGETHER / SEPARATED contiguity modifiers are
ignored here; the full IP / SMT modules handle those.
"""

from collections import defaultdict
from typing import List, Tuple

from .lib.parser import Coords, Hint, Problem
from .lib.puzzle_state import PuzzleState


class PSPR:
    """Puzzle-specific propagation rules — single-hint local reasoning.

    For each hint with scope S and value v, given the cells already known:
      - Let r = v - (known mines in S), u = unknown cells in S.
      - If r == 0:        all cells in u are empty.
      - If r == len(u):   all cells in u are mines.

    Plus the global mine count:
      - If known mines == total_mines: all remaining cells are empty.
      - If remaining cells == remaining mines: all remaining cells are mines.
    """

    name = "pspr"

    def __init__(self, problem: Problem, state: PuzzleState):
        self.problem = problem
        self.state = state

    def step(self) -> List[Tuple[Coords, bool]]:
        known = self.state.known
        forced = {}

        for hint in self.state.available_hints:
            mines_seen = 0
            unknowns = []
            for c in hint.scope:
                if c in known:
                    if known[c]:
                        mines_seen += 1
                else:
                    unknowns.append(c)
            if not unknowns:
                continue
            remaining = hint.value - mines_seen
            if remaining == 0:
                for c in unknowns:
                    forced.setdefault(c, False)
            elif remaining == len(unknowns):
                for c in unknowns:
                    forced.setdefault(c, True)

        total_mines = self.problem.total_mines
        known_mines = sum(1 for v in known.values() if v)
        total_cells = len(self.problem.cells)
        remaining_mines = total_mines - known_mines
        remaining_cells = total_cells - len(known)
        if remaining_cells > 0:
            if remaining_mines == 0:
                for c in self.problem.cells:
                    if c not in known:
                        forced.setdefault(c, False)
            elif remaining_mines == remaining_cells:
                for c in self.problem.cells:
                    if c not in known:
                        forced.setdefault(c, True)

        return list(forced.items())

    def on_reveal(self, coords: Coords, is_mine: bool, unlocked: Hint = None):
        pass


class AC3:
    """Pairwise hint propagation via interval bounds on overlapping scopes.

    For every pair of currently-available hints A, B whose remaining unknown
    scopes share at least one cell:
        common  = unknown(S_A) ∩ unknown(S_B)
        only_A  = unknown(S_A) \\ unknown(S_B)
        only_B  = unknown(S_B) \\ unknown(S_A)
        r_A, r_B = remaining mines needed by A, B
                   (= hint.value minus already-known mines in scope)

    From A alone:  sum(common) ∈ [max(0, r_A - |only_A|), min(r_A, |common|)]
    From B alone:  sum(common) ∈ [max(0, r_B - |only_B|), min(r_B, |common|)]
    Intersect → tight [lo, hi] on sum(common).

    Then for each of `common`, `only_A`, `only_B`:
      - If the maximum possible sum is 0, all cells must be empty.
      - If the minimum possible sum equals the set size, all must be mines.

    Hints are indexed by the unknown cells they touch so only overlapping
    pairs are considered.
    """

    name = "ac3"

    def __init__(self, problem: Problem, state: PuzzleState):
        self.problem = problem
        self.state = state

    def step(self) -> List[Tuple[Coords, bool]]:
        known = self.state.known

        # Per-hint reduced view: unknown cells and remaining mine count.
        hint_info = []
        for h in self.state.available_hints:
            mines_seen = 0
            unknowns = set()
            for c in h.scope:
                if c in known:
                    if known[c]:
                        mines_seen += 1
                else:
                    unknowns.add(c)
            if unknowns:
                hint_info.append((unknowns, h.value - mines_seen))

        # Index hints by the unknown cells they touch.
        cell_to_idx = defaultdict(list)
        for idx, (unk, _r) in enumerate(hint_info):
            for c in unk:
                cell_to_idx[c].append(idx)

        pairs = set()
        for idx_list in cell_to_idx.values():
            n = len(idx_list)
            for i in range(n):
                for j in range(i + 1, n):
                    a, b = idx_list[i], idx_list[j]
                    pairs.add((a, b) if a < b else (b, a))

        forced = {}
        for a, b in pairs:
            ua, ra = hint_info[a]
            ub, rb = hint_info[b]
            common = ua & ub
            if not common:
                continue
            only_a = ua - ub
            only_b = ub - ua

            lo_a = max(0, ra - len(only_a))
            hi_a = min(ra, len(common))
            lo_b = max(0, rb - len(only_b))
            hi_b = min(rb, len(common))
            lo = max(lo_a, lo_b)
            hi = min(hi_a, hi_b)
            if lo > hi:
                continue  # infeasible from these two — let solver handle

            # sum(common) ∈ [lo, hi]
            if hi == 0:
                for c in common:
                    forced.setdefault(c, False)
            elif lo == len(common):
                for c in common:
                    forced.setdefault(c, True)

            # sum(only_A) ∈ [r_a - hi, r_a - lo]
            if only_a:
                max_a = ra - lo
                min_a = ra - hi
                if max_a <= 0:
                    for c in only_a:
                        forced.setdefault(c, False)
                elif min_a >= len(only_a):
                    for c in only_a:
                        forced.setdefault(c, True)

            if only_b:
                max_b = rb - lo
                min_b = rb - hi
                if max_b <= 0:
                    for c in only_b:
                        forced.setdefault(c, False)
                elif min_b >= len(only_b):
                    for c in only_b:
                        forced.setdefault(c, True)

        return list(forced.items())

    def on_reveal(self, coords: Coords, is_mine: bool, unlocked: Hint = None):
        pass
