# The `.hexcells` File Format

The `.hexcells` files found in this repository do **not** represent just the starting state of a puzzle; they represent the **completed, absolute ground truth** of the level. 

Because Hexcells levels generate their hints dynamically based on the surrounding environment, the file must encode exactly where every mine and empty cell is located. When the game (or a solver) loads the file, it:
1. Reads the ground truth (knowing exactly where the mines are).
2. Calculates all the numeric hints (e.g., counting adjacent mines for black cells, counting line totals).
3. Hides the "unrevealed" cells from the player.
4. Challenges the player to deduce the hidden state using the calculated hints and the initially revealed cells.

---

## File Structure

A `.hexcells` file is a plain text file. The structure is strictly defined as follows:

- **Line 1:** Version identifier (e.g., `Hexcells level v1`)
- **Line 2:** The name of the puzzle (e.g., `Something Fishy (Medium)`)
- **Line 3:** The author's name
- **Line 4 & 5:** Empty padding lines
- **Lines 6 to 38:** The 33x33 hex grid.

## The Grid

The grid consists of exactly 33 lines, each containing exactly 66 characters. 
Because the grid uses a staggered coordinate system to represent a hexagonal board in 2D text, each physical cell is represented by **two characters** (a "left" character and a "right" character). 

Empty spaces between cells (due to the staggering) are represented by `..`.

### Left Character: Cell Type & State
The first character of the pair determines what the cell is, and whether it is revealed to the player at the start of the puzzle.

| Character | Meaning |
| :---: | :--- |
| `.` | Empty space (no cell exists here). |
| `o` | **Hidden Black Cell:** An empty cell that does not contain a mine. It is hidden at the start. |
| `O` | **Revealed Black Cell:** An empty cell that does not contain a mine. It is revealed at the start. |
| `x` | **Hidden Blue Cell:** A cell containing a **mine**. It is hidden at the start. |
| `X` | **Revealed Blue Cell:** A cell containing a **mine**. It is revealed at the start. |
| `/` | **Line Constraint (Bottom-Left):** An external hint pointing diagonally down-left. |
| `\` | **Line Constraint (Bottom-Right):** An external hint pointing diagonally down-right. |
| `\|` | **Line Constraint (Bottom):** An external hint pointing straight down. |

### Right Character: Constraints & Modifiers
The second character of the pair defines the constraint modifiers acting upon that cell.

If the left character is a **black cell** (`o` or `O`), the right character defines the hint for its **6 immediate neighbors** (a standard numbered hex).
If the left character is a **blue cell** (`x` or `X`), the right character defines the hint for its **18 extended neighbors** (a blue numbered hex).
If the left character is a **line constraint** (`/`, `\`, `|`), the right character defines the modifier for that line.

| Character | Meaning | In-Game Visual |
| :---: | :--- | :--- |
| `.` | **None:** No constraint or modifier. | *Just a plain cell.* |
| `+` | **Anywhere:** Mines can be anywhere in the scope. | `2` |
| `c` | **Together (Contiguous):** All mines in the scope must be adjacent to each other. | `{2}` |
| `n` | **Separated (Non-Contiguous):** The mines in the scope must be broken up into at least two groups. | `-2-` |

## Example

Let's break down a snippet from a row:
`|+..o...x.../+........../+............`

Splitting this into its 2-character pairs:
1. `|+`: A line constraint pointing straight down (`|`), with standard rules (`+`).
2. `..`: An empty void space in the grid.
3. `o.`: A hidden black cell (`o`) with no constraints (`.`).
4. `..`: An empty void space.
5. `x.`: A hidden blue mine (`x`) with no constraints (`.`).
6. `..`: An empty void space.
7. `/+`: A line constraint pointing down-left (`/`), with standard rules (`+`).

*(Note that the actual numeric value of a constraint, like a "3", is nowhere to be found in the text! As mentioned earlier, the parser must read the ground truth, look at the 6 neighbors around an `o+` cell, and count the `x`s to figure out what number to display to the user).*
