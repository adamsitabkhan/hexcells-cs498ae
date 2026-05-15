# Hexcells Solver

An Algorithmic Engineering study comparing constraint-solving approaches on [Hexcells](https://store.steampowered.com/app/265890/Hexcells/) puzzles. The project includes a modular incremental solver, a procedural level generator, and a benchmarking suite.

---

## Overview

Hexcells puzzles are binary constraint satisfaction problems: each cell is a mine or empty, and numbered hints constrain counts within neighbourhoods and lines. This project explores how different solving strategies — from cheap local propagation to full IP/SMT — compare in speed and coverage.

**Solvers implemented:**
- `PSPR` — (SHP single-hint propagation) puzzle-specific propagation rules
- `AC3` — pairwise interval-bound propagation over overlapping hint scopes
- `Gurobi` — incremental Integer Programming (force-checking via LP)
- `Z3` — incremental SMT (force-checking via push/pop)

All four follow the same module protocol (`step()` / `on_reveal()`) and can be composed freely in the hybrid orchestrator.

---

## Getting Started

### Prerequisites

- Python 3.9+
- [Gurobi Optimizer](https://www.gurobi.com/) with a valid licence (free academic licences available)

### Installation

```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Setup

Initialise reference submodules and apply compatibility patches:

```bash
chmod +x setup_env.sh
./setup_env.sh
```

---

## Repository Structure

```
project/
  solve.py            # Hybrid solver orchestrator (CLI entry point)
  heuristics.py       # PSPR and AC3 heuristic modules
  gurobi_solver.py    # Incremental Gurobi module
  z3_solver.py        # Incremental Z3 module
  lib/
    parser.py         # .hexcells file parser → cube coordinates
    puzzle_state.py   # Tracks known cells and available hints
  viz/
    animate.py        # Step-by-step solve animation + GIF export
    visualize.py      # Static level visualisation

utils/
  benchmark.py        # Run all levels with configurable pipelines
  generate_level.py   # Procedural level generator (single level)
  generate_batch.py   # Batch generation with shape/density sweeps
  gurobi_exact.py     # Exact one-shot Gurobi solver + uniqueness check
  z3_exact.py         # Exact one-shot Z3 solver + uniqueness check
  sort_generated.py   # Sort generated levels into small/medium/large
  migrate_levels.py   # Migrate flat hash-named levels to slug structure
  extract_levels.py   # Extract levels from community sources

testing/
  analysis.py         # Report + plots from benchmark JSONL output

levels/
  small/              # < 100 cells  (301 levels)
  medium/             # 100–299 cells (91 levels)
  large/              # ≥ 300 cells  (24 levels)
  generated/          # index.jsonl — provenance for generated levels

external/
  inventory/          # Community metadata and difficulty rankings
  sixcells/           # Reference Python/Qt player (submodule)
  reference-solver/   # Reference Rust solver (submodule)
```

---

## Usage

### Solve a level

```bash
# Heuristics only
venv/bin/python -m project.solve levels/small/clockwork/level.hexcells \
    --heuristics pspr,ac3

# Heuristics + Gurobi
venv/bin/python -m project.solve levels/medium/corrupted/level.hexcells \
    --heuristics pspr,ac3 --solver gurobi -M 100

# Step-by-step animation
venv/bin/python -m project.solve levels/small/clockwork/level.hexcells \
    --heuristics pspr,ac3 --solver gurobi --viz

# Save animation as GIF
venv/bin/python -m project.solve levels/small/clockwork/level.hexcells \
    --heuristics pspr,ac3 --solver gurobi --gif output.gif
```

**Solver flags:**

| Flag | Description |
|---|---|
| `--heuristics pspr,ac3` | Comma-separated heuristics, run to fixpoint each cycle |
| `--solver gurobi\|z3` | Full solver to run between heuristic fixpoints |
| `-M N` | Max solver iterations per cycle (default 100) |
| `-v` | Verbose per-cycle output |
| `--viz` | Interactive step-by-step animation |
| `--gif PATH` | Save animation to PATH |

### Run the benchmark

```bash
venv/bin/python -m utils.benchmark \
    --heuristics pspr,ac3 --solver gurobi -M 100 \
    --timeout 60 --runs-file testing/runs.jsonl
```

Results are appended to `testing/runs.jsonl` (one record per level). Reruns skip already-logged levels automatically; pass `--no-resume` to override.

### Analyse benchmark results

```bash
venv/bin/python testing/analysis.py               # printed report
venv/bin/python testing/analysis.py --plots       # + saves plots to testing/plots/
```

### Generate levels

```bash
# Single level
venv/bin/python -m utils.generate_level \
    --out levels/small/my-level/level.hexcells \
    --shape hex --size 4 --mine-density 0.4 --minimize --seed 42

# Batch (117 levels, small/medium shapes)
venv/bin/python -m utils.generate_batch

# Batch (76 levels, 50–400 cell range)
venv/bin/python -m utils.generate_batch --large
```

Generation uses the exact solver for uniqueness checking (2 LP calls per candidate), not the incremental solver. The `--minimize` flag greedily hides starter clues while preserving unique solvability, producing harder puzzles.

---

## Benchmarking

The benchmark records per-cycle, per-iteration statistics for each level:

```jsonl
{
  "level_path": "levels/small/clockwork/level.hexcells",
  "config": "h=pspr,ac3;s=gurobi;M=100",
  "elapsed_s": 0.026,
  "determined": 44,
  "total": 44,
  "solved": true,
  "cycles": [
    {
      "cycle": 1,
      "heuristic_steps": [{"module": "pspr", "cells_forced": 3, ...}],
      "solver_steps":    [{"module": "gurobi", "iteration": 1, "cells_forced": 5, ...}]
    }
  ]
}
```

Across 219 levels with the `h=pspr,ac3;s=gurobi;M=100` config:
- **Solve rate:** 187/206 parseable levels (91%)
- **Median time:** 0.021s, mean 0.281s, max 8.3s
- **Heuristic contribution:** median 0%, mean 14% of cells forced per level
- **Speedup over solver-only:** median 1.03×, max 12×

---

## Credits

- **Level corpus:** Community levels sourced via Reddit; metadata from [this Gist](https://gist.github.com/Ngoguey42/a0f661c5cb36180a3a6aca4bb4d385b2) by Ngoguey42.
- **Reference UI:** [`sixcells`](https://github.com/oprypin/sixcells) by oprypin — Python/Qt Hexcells player and editor.
- **Reference solver:** [`hexcells_solver`](https://github.com/Ngoguey42/hexcells_solver) by Ngoguey42 — Rust baseline implementation.

---

*Developed as part of CS498: Algorithmic Engineering.*
