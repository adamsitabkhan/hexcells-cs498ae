# Hexcells Solver

Source code and benchmarks for *CS498-AE Final Project: Solving Hexcells*
(Adam Sitabkhan, May 2026). Compares four automated approaches to the
hexagonal-grid logic puzzle game [Hexcells](https://store.steampowered.com/app/265890/Hexcells/):
a Gurobi integer program, a Z3 SMT formulation, two constraint-propagation
heuristics, and a third-party Rust reference-solver.

---

## Overview

Hexcells puzzles are binary constraint satisfaction problems: each cell is a
mine or empty, and numbered hints constrain mine counts within
neighbourhoods (6-cell ring `ZONE6`, 18-cell halo `ZONE18`) and lines
(`LINE`). The TOGETHER `{n}` and SEPARATED `-n-` modifiers further restrict
mine arrangements.

**Solvers and heuristics (all under [`project/`](project/)):**

| Module | Solver | Description |
|---|---|---|
| `project/gurobi_solver.py`           | `gurobi`     | Incremental Gurobi IP with `quicksum` cardinality + linearised XOR transitions |
| `project/z3_solver.py`               | `z3`         | Incremental Z3 SMT using `z3.PbEq` / `z3.PbGe` for cardinality |
| `project/experiments/z3_qffd.py`     | `z3_qffd`    | `SolverFor("QF_FD")` finite-domain solver on the PbEq encoding |
| `project/experiments/z3_assumptions.py` | `z3_assume` | Assumption-literal `check(p)` in the force-check loop |
| `project/heuristics.py` (`PSPR`)     | `pspr`       | Single-hint propagation (SHP in the report) |
| `project/heuristics.py` (`AC3`)      | `ac3`        | Pairwise interval-bound propagation |

All solvers share the `step()` / `on_reveal()` protocol so they compose
freely in the hybrid orchestrator [`project/solve.py`](project/solve.py).

---

## Setup

### Prerequisites

- **Python 3.9+** (the project was developed on 3.14)
- **[Gurobi Optimizer](https://www.gurobi.com/)** with a valid licence
  (free academic licences are available)
- **[Rust toolchain](https://rustup.rs/)** (`cargo` ≥ 1.70) — only if you
  want to benchmark the Rust reference-solver

### Install Python dependencies

```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Initialise submodules and external tools

```bash
chmod +x setup_env.sh
./setup_env.sh                    # git submodule init + sixcells PyQt5 patch
```

### Build the Rust reference-solver (optional)

```bash
cargo build --release --manifest-path external/reference-solver/Cargo.toml
```

The release binary lands at
`external/reference-solver/target/release/hexcells-solver`.

---

## Reproducing the report

Every benchmark and analysis in the final report is regenerable from this
repository. Each command below appends or overwrites artifacts in
[`testing/`](testing/) and [`figures/`](figures/); none of them touch
`project/` source code.

### 1 — Full-corpus benchmark sweep (Tables 1 and the CDF)

Each configuration runs the 416-level corpus with a 60-second per-level
wall-clock budget. Results are appended (resume-aware) to
`testing/runs.jsonl` keyed by the config string `h=...;s=...;M=...`.

```bash
# Eight configurations from the report (run each once)
for solver in gurobi z3 z3_qffd; do
    venv/bin/python -m utils.benchmark --solver $solver \
        --parallel 4 --timeout 60
    venv/bin/python -m utils.benchmark --solver $solver \
        --heuristics pspr,ac3 --parallel 4 --timeout 60
done

# Heuristics-only baseline
venv/bin/python -m utils.benchmark \
    --heuristics pspr,ac3 --parallel 4 --timeout 60

# Rust reference-solver (requires the cargo build above)
venv/bin/python -m utils.run_rust_solver --parallel 4 --timeout 60
```

Each command is idempotent: re-running skips configs already complete for
each level. Pass `--no-resume` to override, or `--category small|medium|large`
to scope to one tier.

### 2 — Summary tables and per-level diffs

```bash
# Master coverage / median / p90 table across every config in runs.jsonl
venv/bin/python -m utils.summarize_runs

# Filter to specific configs (repeat --configs per key; commas in keys)
venv/bin/python -m utils.summarize_runs \
    --configs "h=none;s=gurobi;M=100" \
    --configs "h=none;s=z3;M=100"

# Per-level ratio + biggest speedups/regressions between two configs
venv/bin/python -m utils.summarize_runs \
    --diff "base=h=none;s=gurobi;M=100,cmp=h=none;s=rust;M=na"
```

### 3 — Z3 diagnostic and pathological-level profiling (Section *Where Z3 loses*)

```bash
# The original Phase 1 diagnostic (small/medium representative levels);
# writes testing/z3_profile.md
venv/bin/python -m utils.profile_z3

# Profile a single pathological level (e.g. modulo-mediumhard or sorcerer);
# writes testing/z3_pathological_<slug>.md
venv/bin/python -m utils.profile_z3 \
    --level levels/small/modulo-mediumhard/level.hexcells \
    --max-iters 50

# Head-to-head of Z3 variants on a handful of representative levels
venv/bin/python -m utils.compare_z3_variants --skip-large --timeout 120
```

### 4 — Generate figures

```bash
# Regenerates every PNG in figures/ from testing/runs.jsonl
venv/bin/python -m utils.generate_figures
```

### 5 — Solve and visualise a single level

```bash
# Heuristics + Gurobi, with an interactive solve animation
venv/bin/python -m project.solve \
    levels/small/clockwork/level.hexcells \
    --heuristics pspr,ac3 --solver gurobi --viz

# Save the animation as a GIF
venv/bin/python -m project.solve \
    levels/small/clockwork/level.hexcells \
    --heuristics pspr,ac3 --solver gurobi --gif clockwork.gif
```

### 6 — Generate new procedural levels (optional)

```bash
# Single level
venv/bin/python -m utils.generate_level \
    --out levels/small/my-level/level.hexcells \
    --shape hex --size 4 --mine-density 0.4 --minimize --seed 42

# Batch (197 levels)
venv/bin/python -m utils.generate_batch
venv/bin/python -m utils.sort_generated  # sort into small/medium/large
```

Generation uses the exact one-shot solver
([`utils/gurobi_exact.py`](utils/gurobi_exact.py)) for uniqueness checking
(2 LP calls per candidate). `--minimize` greedily hides starter clues while
preserving unique solvability.

---

## Repository layout

```
project/
  solve.py                       # Hybrid solver orchestrator (CLI entry point)
  gurobi_solver.py               # Incremental Gurobi module
  z3_solver.py                   # Incremental Z3 module (PbEq encoding)
  heuristics.py                  # PSPR / SHP and AC3
  experiments/                   # Z3 ablation variants
    z3_assumptions.py            # Assumption-literal force-check loop
    z3_qffd.py                   # QF_FD finite-domain solver
  lib/
    parser.py                    # .hexcells file parser → cube coordinates
    puzzle_state.py              # Tracks known cells and available hints
  viz/
    animate.py                   # Step-by-step solve animation + GIF export
    visualize.py                 # Static level visualisation

utils/
  benchmark.py                   # Run all levels with configurable pipelines
  run_rust_solver.py             # Drive the Rust reference-solver under timeout
  summarize_runs.py              # Coverage / median / p90 tables + diffs
  profile_z3.py                  # Per-iteration timing + Z3 statistics() deltas
  compare_z3_variants.py         # Head-to-head of Z3 variants on a few levels
  generate_figures.py            # PNGs from runs.jsonl
  gurobi_exact.py / z3_exact.py  # Exact one-shot solvers (uniqueness check)
  generate_level.py / generate_batch.py / sort_generated.py
                                 # Procedural level generation
  extract_levels.py / migrate_levels.py
                                 # Community-level ingestion / reorganisation

testing/
  runs.jsonl                     # Full benchmark log (config × level)
  z3_profile.md                  # Phase-1 Z3 diagnostic writeup
  z3_pathological_*.md           # Per-level profiles of the Z3 outliers

levels/
  small/    (301 levels, < 100 cells)
  medium/   (91  levels, 100–299 cells)
  large/    (24  levels, ≥ 300 cells)
  generated/index.jsonl          # Provenance for procedurally generated levels

external/                        # Git submodules
  reference-solver/              # Goguey's Rust solver
  sixcells/                      # oprypin's Hexcells player + editor
  inventory/                     # Community metadata + difficulty rankings

figures/                         # Benchmark figures (generated PNGs)
```

---

## Headline benchmark results

416-level corpus, 60-second timeout, 4 parallel workers:

| Config | small (/301) | medium (/91) | large (/24) | total | geomean vs Gurobi |
|---|---:|---:|---:|---:|---:|
| Gurobi IP            | 277 | 82 | 24 | 383 | 1.00× |
| Z3 (PbEq)            | 276 | 80 | 21 | 377 | 1.43× |
| Z3-QFFD              | 277 | 82 | 24 | 383 | 1.50× |
| Rust reference       | 277 | 85 | 24 | **386** | **0.33×** |
| Heuristics only (SHP+AC3) | 79 | 42 | 18 | 139 | — |

The PbEq encoding promotion alone took Z3 from 50–170× slower than Gurobi
on large puzzles to ~1.5× slower at geomean.

---

## Credits

- **Course:** CS498 Algorithmic Engineering, taught by Elfarouk Harb,
  Spring 2026.
- **Hexcells format and editor:**
  [`sixcells`](https://github.com/oprypin/sixcells) by Oleh Prypin —
  Python/Qt player and editor; defines the `.hexcells` text format used
  throughout this project.
- **Rust reference-solver:**
  [`hexcells-solver`](https://github.com/Ngoguey42/hexcells-solver) by
  Francois Goguey (Ngoguey42) — used as a third-party baseline and a
  ground-truth difficulty metric.
- **Level corpus:** Community puzzles from
  [r/hexcellslevels](https://www.reddit.com/r/hexcellslevels/); metadata
  and difficulty rankings from
  [Ngoguey42's Gist](https://gist.github.com/Ngoguey42/a0f661c5cb36180a3a6aca4bb4d385b2).
- **Solver backends:** [Gurobi Optimizer](https://www.gurobi.com/) and
  [Z3](https://github.com/Z3Prover/z3).
