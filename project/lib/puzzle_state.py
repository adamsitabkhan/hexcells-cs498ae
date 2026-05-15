"""Tracks the player-visible state of a Hexcells puzzle during iterative solving.

At the start, only cells with `revealed=True` are known to the player, along
with the LINE hints (external markers that are always visible). As cells are
deduced and "revealed", any hint attached to them becomes newly available
as an additional constraint.
"""

from typing import Dict, List, Optional, Set

from .parser import Cell, CellType, Coords, Hint, Problem


class PuzzleState:
    def __init__(self, problem: Problem):
        self.problem = problem
        self.known: Dict[Coords, bool] = {}
        self.available_hints: List[Hint] = []
        self.pending_hints: Dict[Coords, Hint] = {}

        for hint in problem.hints:
            if hint.type == CellType.LINE:
                self.available_hints.append(hint)
            else:
                self.pending_hints[hint.coords] = hint

        for coords, cell in problem.cells.items():
            if cell.revealed:
                is_mine = coords in problem.mines
                self._record_reveal(coords, is_mine)

    def reveal(self, coords: Coords, is_mine: bool) -> Optional[Hint]:
        """Record that cell `coords` has been deduced. Returns the newly
        unlocked hint, if any."""
        if coords in self.known:
            if self.known[coords] != is_mine:
                raise ValueError(
                    f"Conflicting reveal at {coords}: prior={self.known[coords]}, new={is_mine}"
                )
            return None
        return self._record_reveal(coords, is_mine)

    def _record_reveal(self, coords: Coords, is_mine: bool) -> Optional[Hint]:
        self.known[coords] = is_mine
        if coords in self.pending_hints:
            hint = self.pending_hints.pop(coords)
            self.available_hints.append(hint)
            return hint
        return None

    def unknown_cells(self) -> Set[Coords]:
        return set(self.problem.cells.keys()) - set(self.known.keys())

    def is_complete(self) -> bool:
        return len(self.known) == len(self.problem.cells)

    def known_mine_count(self) -> int:
        return sum(1 for v in self.known.values() if v)
