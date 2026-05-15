import enum
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

class Color(enum.Enum):
    BLACK = "black"
    BLUE = "blue"

class Modifier(enum.Enum):
    ANYWHERE = "anywhere"
    TOGETHER = "together"
    SEPARATED = "separated"

class Orientation(enum.Enum):
    BOTTOM_RIGHT = "bottom_right"
    BOTTOM = "bottom"
    BOTTOM_LEFT = "bottom_left"

class CellType(enum.Enum):
    EMPTY = "empty"
    ZONE0 = "zone0" # Regular cell
    ZONE6 = "zone6" # Numbered cell (6 neighbors)
    ZONE18 = "zone18" # Numbered cell (18 neighbors)
    LINE = "line" # Column constraint

@dataclass(frozen=True, order=True)
class Coords:
    q: int
    r: int
    s: int

    def __post_init__(self):
        if self.q + self.r + self.s != 0:
            raise ValueError(f"Invalid cube coordinates: {self.q}, {self.r}, {self.s}")

    def neighbors6(self) -> List['Coords']:
        q, r, s = self.q, self.r, self.s
        return [
            Coords(q + 0, r - 1, s + 1), # top
            Coords(q + 1, r - 1, s + 0), # top-right
            Coords(q + 1, r + 0, s - 1), # bot-right
            Coords(q + 0, r + 1, s - 1), # bot
            Coords(q - 1, r + 1, s + 0), # bot-left
            Coords(q - 1, r + 0, s + 1), # top-left
        ]

    def neighbors18(self) -> List['Coords']:
        q, r, s = self.q, self.r, self.s
        return [
            Coords(q + 0, r - 1, s + 1),
            Coords(q + 1, r - 1, s + 0),
            Coords(q + 1, r + 0, s - 1),
            Coords(q + 0, r + 1, s - 1),
            Coords(q - 1, r + 1, s + 0),
            Coords(q - 1, r + 0, s + 1),
            Coords(q + 0, r - 2, s + 2),
            Coords(q + 1, r - 2, s + 1),
            Coords(q + 2, r - 2, s + 0),
            Coords(q + 2, r - 1, s - 1),
            Coords(q + 2, r + 0, s - 2),
            Coords(q + 1, r + 1, s - 2),
            Coords(q + 0, r + 2, s - 2),
            Coords(q - 1, r + 2, s - 1),
            Coords(q - 2, r + 2, s + 0),
            Coords(q - 2, r + 1, s + 1),
            Coords(q - 2, r + 0, s + 2),
            Coords(q - 1, r - 1, s + 2),
        ]

@dataclass
class Cell:
    type: CellType
    revealed: bool = False
    color: Optional[Color] = None
    modifier: Optional[Modifier] = None
    orientation: Optional[Orientation] = None

def parse_hexcells(file_path: str) -> Dict[Coords, Cell]:
    with open(file_path, 'r') as f:
        lines = f.readlines()
    
    if len(lines) < 38:
        raise ValueError(f"File {file_path} is too short ({len(lines)} lines)")
    
    # Header info
    level_name = lines[1].strip()
    author = lines[2].strip()
    
    # Grid starts at line 5 (0-indexed)
    grid_lines = [line.strip('\r\n') for line in lines[5:38]]
    
    raw_grid: List[List[Tuple[str, str]]] = []
    for line in grid_lines:
        if len(line) != 66:
            # Pad or raise error? Rust raises error.
            raise ValueError(f"Line length expected 66, got {len(line)}")
        
        row = []
        for j in range(0, 66, 2):
            row.append((line[j], line[j+1]))
        raw_grid.append(row)

    def parse_modifier(r: str) -> Modifier:
        if r == '+': return Modifier.ANYWHERE
        if r == 'c': return Modifier.TOGETHER
        if r == 'n': return Modifier.SEPARATED
        raise ValueError(f"Invalid modifier: {r}")

    def get_cell(left: str, right: str) -> Cell:
        if left == '.' and right == '.':
            return Cell(CellType.EMPTY)
        
        if left == 'o': # Hidden black
            if right == '.':
                return Cell(CellType.ZONE0, revealed=False, color=Color.BLACK)
            return Cell(CellType.ZONE6, revealed=False, color=Color.BLACK, modifier=parse_modifier(right))

        if left == 'O': # Revealed black
            if right == '.':
                return Cell(CellType.ZONE0, revealed=True, color=Color.BLACK)
            return Cell(CellType.ZONE6, revealed=True, color=Color.BLACK, modifier=parse_modifier(right))
        
        if left == 'x': # Hidden blue
            if right == '.':
                return Cell(CellType.ZONE0, revealed=False, color=Color.BLUE)
            if right == '+':
                return Cell(CellType.ZONE18, revealed=False, color=Color.BLUE)

        if left == 'X': # Revealed blue
            if right == '.':
                return Cell(CellType.ZONE0, revealed=True, color=Color.BLUE)
            if right == '+':
                return Cell(CellType.ZONE18, revealed=True, color=Color.BLUE)
        
        if left == '/':
            return Cell(CellType.LINE, orientation=Orientation.BOTTOM_LEFT, modifier=parse_modifier(right))
        if left == '\\':
            return Cell(CellType.LINE, orientation=Orientation.BOTTOM_RIGHT, modifier=parse_modifier(right))
        if left == '|':
            return Cell(CellType.LINE, orientation=Orientation.BOTTOM, modifier=parse_modifier(right))
        
        raise ValueError(f"Unknown cell type: {left}{right}")

    cell_grid: List[List[Cell]] = []
    for r in range(33):
        row = []
        for c in range(33):
            left, right = raw_grid[r][c]
            row.append(get_cell(left, right))
        cell_grid.append(row)

    # Convert to cube coordinates
    def convert_grid(alignment: str) -> Dict[Coords, Cell]:
        icorrection = 1 if alignment == "even" else 0
        jcorrection = 0
        
        res = {}
        for i in range(33):
            ii = i + icorrection
            for j in range(33):
                jj = j + jcorrection
                
                # Formula from Rust:
                # q = 0.0 * i + 1.0 * j
                # r = 0.5 * i - 0.5 * j
                # s = -0.5 * i - 0.5 * j
                
                q_f = float(jj)
                r_f = 0.5 * ii - 0.5 * jj
                s_f = -0.5 * ii - 0.5 * jj
                
                # Check if it lands on a whole coordinate
                # q.fract() == 0. && s.fract() == 0.
                if q_f.is_integer() and s_f.is_integer():
                    cell = cell_grid[i][j]
                    if cell.type != CellType.EMPTY:
                        coords = Coords(int(q_f), int(r_f), int(s_f))
                        res[coords] = cell
                else:
                    # If not whole, MUST be empty
                    if cell_grid[i][j].type != CellType.EMPTY:
                        raise ValueError("Bad alignment")
        return res

    try:
        return convert_grid("even")
    except ValueError:
        return convert_grid("odd")

@dataclass
class Hint:
    coords: Coords
    value: int
    modifier: Modifier
    type: CellType
    scope: List[Coords]

class Problem:
    def __init__(self, level: Dict[Coords, Cell]):
        self.level = level
        self.cells = {c: cell for c, cell in level.items() if cell.type in (CellType.ZONE0, CellType.ZONE6, CellType.ZONE18)}
        self.mines = {c for c, cell in self.cells.items() if cell.color == Color.BLUE}
        self.hints: List[Hint] = []
        self.total_mines = len(self.mines)
        
        self._calculate_hints()

    def _calculate_hints(self):
        for coords, cell in self.level.items():
            if cell.type == CellType.ZONE6:
                scope = [c for c in coords.neighbors6() if c in self.cells]
                mine_count = sum(1 for c in scope if c in self.mines)
                self.hints.append(Hint(coords, mine_count, cell.modifier, cell.type, scope))
            
            elif cell.type == CellType.ZONE18:
                scope = [c for c in coords.neighbors18() if c in self.cells]
                mine_count = sum(1 for c in scope if c in self.mines)
                self.hints.append(Hint(coords, mine_count, Modifier.ANYWHERE, cell.type, scope))
            
            elif cell.type == CellType.LINE:
                scope = self._get_line_scope(coords, cell.orientation)
                mine_count = sum(1 for c in scope if c in self.mines)
                self.hints.append(Hint(coords, mine_count, cell.modifier, cell.type, scope))

    def _get_line_scope(self, coords: Coords, orientation: Orientation) -> List[Coords]:
        dq, dr, ds = {
            Orientation.BOTTOM: (0, 1, -1),
            Orientation.BOTTOM_RIGHT: (1, 0, -1),
            Orientation.BOTTOM_LEFT: (-1, 1, 0)
        }[orientation]
        
        scope = []
        # Max dimension is around 33
        for i in range(1, 34):
            c = Coords(coords.q + dq * i, coords.r + dr * i, coords.s + ds * i)
            if c in self.cells:
                scope.append(c)
        return scope

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        path = sys.argv[1]
        try:
            level = parse_hexcells(path)
            problem = Problem(level)
            print(f"Parsed {len(level)} total objects from {path}")
            print(f"Active cells: {len(problem.cells)}")
            print(f"Total mines: {problem.total_mines}")
            print(f"Hints found: {len(problem.hints)}")
            
            # Print a few hints
            for i, hint in enumerate(problem.hints[:5]):
                print(f"Hint at {hint.coords}: {hint.value} mines (modifier: {hint.modifier.value}, type: {hint.type.value})")
                print(f"  Scope size: {len(hint.scope)}")
        except Exception as e:
            import traceback
            traceback.print_exc()
