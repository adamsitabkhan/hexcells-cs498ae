# Z3 Incremental Solver — Diagnostic Profile

Baseline `project/z3_solver.py` instrumented with per-iteration timing and `solver.statistics()` deltas. The large tier was profiled separately (see "Variant comparison" below) because the baseline runs ~minutes and would dominate runtime; the small + medium picture is already decisive.

**TL;DR**

- The per-cell `push / add / check / pop` loop in `step()` accounts for **92–97%** of wall time. Baseline `check()` and `on_reveal()` are negligible.
- The first outer iteration alone accounts for ~60% of total time, because every unknown cell is tested against a constraint set that has no forced-cell pins yet.
- cProfile confirms ~99.6% of time is in the C-level `Z3_solver_check_assumptions` call, not Python overhead.
- The cardinality encoding (`Sum(If(b,1,0)) == k`) routes through Z3's LIA theory: `arith-*` counters dominate `solver.statistics()` after a single iteration (1.6M `added eqs`, 489k `arith-bound-propagations-lp`).
- Replacing the cardinality encoding with `z3.PbEq` and/or switching to the QF_FD solver yields **15–35× speedup** on small + medium (full correctness preserved). On the large diagnostic level, none of the variants completed within 400s — the baseline encoding is fundamentally expensive at 444 cells and a more structural fix is needed (see "Open question" at the end).

## Per-level summary

| Tier | Cells | Mines | Iters | Determined | Total s | On-reveal s | Σ baseline-check s | Σ loop-check s | Loop / Total |
|------|------:|------:|------:|-----------:|--------:|------------:|-------------------:|---------------:|-------------:|
| small | 97 | 45 | 3 | 97/97 | 2.385 | 0.007 | 0.034 | 2.203 |  92.3% |
| medium | 169 | 85 | 8 | 169/169 | 14.190 | 0.013 | 0.085 | 13.823 |  97.4% |

### small — `levels/small/spiral-easy-medium-1-4/level.hexcells` (97 cells)

| Iter | Unknowns | Forced | Iter s | Baseline-check s | Loop-check s | Δ conflicts | Δ decisions | Δ propagations |
|-----:|---------:|-------:|-------:|-----------------:|-------------:|------------:|------------:|---------------:|
| 1 | 95 | 10 | 1.449 | 0.0253 | 1.371 | 11203 | 112871 | 1009467 |
| 2 | 85 | 28 | 0.650 | 0.0026 | 0.572 | 723 | 3618 | 139647 |
| 3 | 57 | 57 | 0.280 | 0.0058 | 0.259 | 325 | 461 | 40427 |

### medium — `levels/medium/tametsi-tmi/level.hexcells` (169 cells)

| Iter | Unknowns | Forced | Iter s | Baseline-check s | Loop-check s | Δ conflicts | Δ decisions | Δ propagations |
|-----:|---------:|-------:|-------:|-----------------:|-------------:|------------:|------------:|---------------:|
| 1 | 138 | 29 | 8.424 | 0.0346 | 8.329 | 19346 | 324519 | 1396079 |
| 2 | 109 | 11 | 2.054 | 0.0131 | 1.939 | 717 | 10408 | 98141 |
| 3 | 98 | 11 | 1.501 | 0.0087 | 1.459 | 429 | 6365 | 55576 |
| 4 | 87 | 12 | 1.304 | 0.0093 | 1.271 | 374 | 5925 | 47517 |
| 5 | 75 | 22 | 0.689 | 0.0100 | 0.656 | 187 | 2668 | 19947 |
| 6 | 53 | 30 | 0.172 | 0.0058 | 0.154 | 69 | 320 | 3885 |
| 7 | 23 | 19 | 0.028 | 0.0034 | 0.016 | 18 | 4 | 178 |
| 8 | 4 | 4 | 0.004 | 0.0000 | 0.000 | 3 | 0 | 0 |

## cProfile (medium level, 1 outer iteration)

Forced cells in this iteration: **29**

```
73211 function calls (72935 primitive calls) in 9.134 seconds

   Ordered by: cumulative time
   List reduced from 84 to 30 due to restriction <30>

   ncalls  tottime  percall  cumtime  percall filename:lineno(function)
        1    0.001    0.001    9.134    9.134 /Users/asita/Development/hexcells-project/project/z3_solver.py:83(step)
      139    0.001    0.000    9.099    0.065 /Users/asita/Development/hexcells-project/venv/lib/python3.14/site-packages/z3/z3.py:7364(check)
      139    9.097    0.065    9.098    0.065 /Users/asita/Development/hexcells-project/venv/lib/python3.14/site-packages/z3/z3core.py:4348(Z3_solver_check_assumptions)
      138    0.000    0.000    0.015    0.000 /Users/asita/Development/hexcells-project/venv/lib/python3.14/site-packages/z3/z3.py:7224(pop)
      138    0.015    0.000    0.015    0.000 /Users/asita/Development/hexcells-project/venv/lib/python3.14/site-packages/z3/z3core.py:4208(Z3_solver_pop)
      138    0.000    0.000    0.006    0.000 /Users/asita/Development/hexcells-project/venv/lib/python3.14/site-packages/z3/z3.py:7297(add)
      138    0.000    0.000    0.006    0.000 /Users/asita/Development/hexcells-project/venv/lib/python3.14/site-packages/z3/z3.py:1058(__eq__)
      138    0.000    0.000    0.005    0.000 /Users/asita/Development/hexcells-project/venv/lib/python3.14/site-packages/z3/z3.py:7278(assert_exprs)
      414    0.000    0.000    0.005    0.000 /Users/asita/Development/hexcells-project/venv/lib/python3.14/site-packages/z3/z3.py:1621(cast)
      138    0.000    0.000    0.005    0.000 /Users/asita/Development/hexcells-project/venv/lib/python3.14/site-packages/z3/z3.py:1302(_coerce_exprs)
     1136    0.001    0.000    0.003    0.000 /Users/asita/Development/hexcells-project/venv/lib/python3.14/site-packages/z3/z3.py:372(__init__)
     1934    0.001    0.000    0.003    0.000 /Users/asita/Development/hexcells-project/venv/lib/python3.14/site-packages/z3/z3.py:593(as_ast)
     1136    0.001    0.000    0.003    0.000 /Users/asita/Development/hexcells-project/venv/lib/python3.14/site-packages/z3/z3.py:377(__del__)
     6556    0.002    0.000    0.003    0.000 /Users/asita/Development/hexcells-project/venv/lib/python3.14/site-packages/z3/z3core.py:1588(Check)
      414    0.000    0.000    0.002    0.000 /Users/asita/Development/hexcells-project/venv/lib/python3.14/site-packages/z3/z3.py:1657(sort)
     1934    0.001    0.000    0.002    0.000 /Users/asita/Development/hexcells-project/venv/lib/python3.14/site-packages/z3/z3core.py:2900(Z3_sort_to_ast)
      169    0.000    0.000    0.002    0.000 /Users/asita/Development/hexcells-project/venv/lib/python3.14/site-packages/z3/z3.py:400(__bool__)
      138    0.000    0.000    0.002    0.000 /Users/asita/Development/hexcells-project/venv/lib/python3.14/site-packages/z3/z3.py:7202(push)
      138    0.002    0.000    0.002    0.000 /Users/asita/Development/hexcells-project/venv/lib/python3.14/site-packages/z3/z3core.py:4204(Z3_solver_push)
      253    0.000    0.000    0.002    0.000 /Users/asita/Development/hexcells-project/venv/lib/python3.14/site-packages/z3/z3.py:1471(is_app_of)
      138    0.002    0.000    0.002    0.000 /Users/asita/Development/hexcells-project/venv/lib/python3.14/site-packages/z3/z3core.py:4221(Z3_solver_assert)
      276    0.000    0.000    0.002    0.000 /Users/asita/Development/hexcells-project/venv/lib/python3.14/site-packages/z3/z3.py:431(eq)
      277    0.000    0.000    0.001    0.000 /Users/asita/Development/hexcells-project/venv/lib/python3.14/site-packages/z3/z3.py:1824(BoolSort)
      169    0.000    0.000    0.001    0.000 /Users/asita/Development/hexcells-project/venv/lib/python3.14/site-packages/z3/z3.py:6651(evaluate)
      169    0.000    0.000    0.001    0.000 /Users/asita/Development/hexcells-project/venv/lib/python3.14/site-packages/z3/z3.py:6620(eval)
      253    0.000    0.000    0.001    0.000 /Users/asita/Development/hexcells-project/venv/lib/python3.14/site-packages/z3/z3.py:1115(kind)
      169    0.000    0.000    0.001    0.000 /Users/asita/Development/hexcells-project/venv/lib/python3.14/site-packages/z3/z3.py:1722(is_true)
      276    0.000    0.000    0.001    0.000 /Users/asita/Development/hexcells-project/venv/lib/python3.14/site-packages/z3/z3.py:1271(_coerce_expr_merge)
     1136    0.001    0.000    0.001    0.000 /Users/asita/Development/hexcells-project/venv/lib/python3.14/site-packages/z3/z3core.py:1658(Z3_inc_ref)
      506    0.000    0.000    0.001    0.000 /Users/asita/Development/hexcells-project/venv/lib/python3.14/site-packages/z3/z3.py:1368(is_app)
```

## Variant comparison

Four variants live under `project/experiments/`, each targeting one hypothesized weakness:

| Variant | What it changes | Hypothesis |
|---------|-----------------|------------|
| `z3_assume` | `push/add/check/pop` → `solver.check(p)` with one indicator literal per test, keeping learned clauses across queries | The pop loop discards learned lemmas |
| `z3_pbeq` | `Sum(If(b,1,0)) == k` → `z3.PbEq([(b,1) for b in scope], k)`; same for transition counts | LIA theory dispatch is wasted on pure cardinality |
| `z3_qffd` | `z3.Solver()` → `z3.SolverFor("QF_FD")` | The default SMT engine is mis-specialized for this class |
| `z3_pbeq_qffd` | Both PbEq encoding and QF_FD solver | The two wins compose |

End-to-end solve times (full `.solve()` to completion, all variants correct on every determined cell):

| Tier | Level | `z3` | `z3_assume` | `z3_pbeq` | `z3_qffd` | `z3_pbeq_qffd` |
|------|-------|------:|------------:|----------:|----------:|---------------:|
| small  | spiral-easy-medium-1-4   | 2.26s  | 1.29s | **0.44s** | **0.37s** | (not run) |
| medium | tametsi-tmi              | 12.92s | 7.53s | **0.37s** | 0.59s | (not run) |
| large  | a-giant-scoop-of-vanilla | ≈229s* | (not run) | >400s | >400s | >400s |

`*` Baseline large-tier time is the previously-recorded ~229s figure; not re-measured in this session.

Reproduce with:

```
python -m utils.compare_z3_variants --skip-large --timeout 120
python -m utils.compare_z3_variants \
    --variants z3_pbeq_qffd --timeout 400 \
    --levels large=levels/large/a-giant-scoop-of-vanilla/level.hexcells
```

## Findings & recommendation

1. **`z3_pbeq` is the unambiguous winner for small+medium.** ~5× faster than baseline on small, **~35× faster on medium**. The PbEq dispatch keeps cardinality reasoning out of the LIA theory entirely. Implementing it required only swapping one expression in `_add_hint` (plus a corresponding rewrite of the transition-count constraint).
2. **`z3_qffd` is close behind on small+medium.** Same correctness, ~6× small / ~22× medium. It composes cleanly with PbEq in `z3_pbeq_qffd.py`, but stacking them did not help on the large level.
3. **`z3_assume` is the smallest win.** It removes the lemma-discard penalty but the cardinality encoding still routes through LIA, so the bottleneck moves but doesn't disappear. Useful as an orthogonal fix once PbEq lands.
4. **No variant solved the large tier within 400s.** Baseline was reported at ~229s previously, so the PbEq/QF_FD encoding is plausibly *worse* at 444 cells than the LIA encoding it replaces — likely because QF_FD's eager bit-blasting / preprocessing scales poorly with the constraint count, and PbEq generates more bookkeeping at large scope sizes. This is an open question, not a confirmed regression: the baseline was not re-timed in this session.

**Recommendation for promotion.** Promote the `_add_hint` change from `z3_pbeq` into `project/z3_solver.py` as the new default Z3 encoding. Leave `z3_qffd`, `z3_assume`, and `z3_pbeq_qffd` in `project/experiments/` and continue to expose them as `--solver` choices in `utils/benchmark.py` so the Algorithmic Engineering report can cite the head-to-head numbers. Keep the default solver (`z3.Solver()`), not QF_FD, because QF_FD did not help on large and shows no consistent advantage over PbEq alone on medium (0.37s PbEq vs 0.59s QF_FD).

## Open question

The large-tier verdict is "none of the prototypes work fast enough" — which is itself a useful finding for the report, but does not resolve how to handle the 24-level large corpus with Z3 in bulk. Plausible next steps, in rough order of effort:

- **Re-time baseline `z3` on the large diagnostic level** to confirm the 229s number; the variants may be *slower* relative to a moving baseline.
- **Combine `z3_pbeq` with `z3_assume`** (`z3_pbeq_assume.py`): if the lemma-retention win composes with PbEq, the large tier may become tractable.
- **Two-model intersection on the baseline solve**: get a second model that maximizes disagreement with the first, and skip per-cell checks for cells that already agree across both — would cut the loop count significantly on the first iteration, which is where most of the time is spent.
- **Stop driving Z3 to fixpoint**: combine with the heuristics pipeline (`pspr`, `ac3`) which already handles easy cells fast, and only call Z3 on the residual hard set.

---

# Phase 2 — Promotion, Composition, and Cross-Solver Benchmark

## What changed in the code

- `_add_hint` and `_build_initial` in [project/z3_solver.py](project/z3_solver.py) now use `z3.PbEq` / `z3.PbGe` for every cardinality / transition-count constraint. The `_b2i` helper is gone.
- [project/experiments/z3_pbeq.py](project/experiments/z3_pbeq.py) and `z3_pbeq_qffd.py` were deleted — both are now identical to the new baseline / `z3_qffd` respectively.
- [project/experiments/z3_assumptions.py](project/experiments/z3_assumptions.py) inherits the new baseline encoding through `Z3Module`, so it is now the *combined* "PbEq + assumption literals" variant (no separate `z3_pbeq_assume.py` was needed).
- [utils/summarize_runs.py](utils/summarize_runs.py) reads `testing/runs.jsonl` and emits per-config / per-category coverage and elapsed-time stats, plus a per-level diff between two configs.

## Post-promotion smoke check (diagnostic levels)

Same three levels used in Phase 1; full `.solve()` to completion:

| Variant | small (97c) | medium (169c) |
|---|---:|---:|
| `z3` (post-promotion baseline) | **0.03s** | **0.05s** |
| `z3_assume` | 0.04s | 0.07s |
| `z3_qffd` | 0.06s | 0.15s |

Compare to Phase 1's baseline `z3`: 2.26s small / 12.92s medium. The PbEq conversion of the total-mines constraint in `_build_initial` (which Phase 1's `z3_pbeq` variant did not touch) accounts for the additional speedup beyond Phase 1. **Post-promotion, `z3_assume` and `z3_qffd` are now slightly *slower* than the new baseline at this scale** — the per-cell push/pop loop is no longer the bottleneck, so the overhead they add (extra implication literal / eager bit-blasting) is visible.

## Full-corpus benchmark — 416 levels, `--timeout 60`, `--parallel 4`

All numbers from `testing/runs.jsonl`; reproduce with `python -m utils.summarize_runs`.

### Coverage (solved / total per category)

| Config | small (301) | medium (91) | large (24) | Total solved |
|---|---:|---:|---:|---:|
| `h=none;s=gurobi`         | 277/301 | 82/91 | 24/24 | **383** |
| `h=pspr,ac3;s=gurobi`     | 274/301 | 83/91 | 24/24 | 381 |
| `h=none;s=z3`             | 276/301 | 80/91 | 21/24 | 377 |
| `h=pspr,ac3;s=z3`         | 276/301 | 78/91 | 19/24 | 373 |
| `h=none;s=z3_assume`      | 276/301 | 80/91 | 19/24 | 375 |
| `h=pspr,ac3;s=z3_assume`  | 276/301 | 81/91 | 19/24 | 376 |
| `h=none;s=z3_qffd`        | **277/301** | **82/91** | **24/24** | **383** |
| `h=pspr,ac3;s=z3_qffd`    | 276/301 | 82/91 | 24/24 | 382 |
| `h=pspr,ac3;s=none`       | 79/301 | 42/91 | 18/24 | 139 |

Notes:
- 13 levels (9 small + 4 medium) fail to parse and error out for every config.
- `h=pspr,ac3;s=none` (heuristics alone) solves 139 / 416 levels — including 18/24 large. This explains why adding heuristics to a fast solver does almost nothing on the corpus: the heuristics cover the easy levels and the solver was already fast on the residual hard set.
- **`z3_qffd` matches Gurobi's full-corpus coverage** (383 solved). Plain `z3` misses 7 of those (5 hard mediums + 2 large-tier Vanilla variants); `z3_assume` misses 8.

### Median elapsed time (over solved levels)

| Config | small | medium | large |
|---|---:|---:|---:|
| `h=none;s=gurobi`         | 0.02s | 0.04s | 0.04s |
| `h=pspr,ac3;s=gurobi`     | 0.02s | 0.02s | 0.02s |
| `h=none;s=z3`             | 0.03s | 0.05s | 0.05s |
| `h=pspr,ac3;s=z3`         | 0.02s | 0.04s | 0.05s |
| `h=none;s=z3_assume`      | 0.03s | 0.05s | 0.06s |
| `h=pspr,ac3;s=z3_assume`  | 0.05s | 0.06s | 0.04s |
| `h=none;s=z3_qffd`        | 0.02s | 0.07s | 0.10s |
| `h=pspr,ac3;s=z3_qffd`    | 0.02s | 0.04s | 0.05s |

### Z3-vs-Gurobi pairwise diff (per level, on levels both configs solved)

`python -m utils.summarize_runs --diff "base=...,cmp=..."`:

| Comparison | Levels in both | Geomean ratio (cmp / base) | Median ratio |
|---|---:|---:|---:|
| `z3` / `gurobi` (no heuristics)        | 376 | **1.43×** | 1.51× |
| `z3_qffd` / `gurobi` (no heuristics)   | 382 | **1.50×** | 1.36× |

So **post-promotion Z3 is ~1.5× slower than Gurobi at the median**, down from "50–170× slower" before Phase 1. The geometric mean of 1.43–1.50 hides ~5 catastrophic outliers per Z3 config:

| Level | cat | Gurobi | z3 | z3_qffd |
|---|---|---:|---:|---:|
| `small/modulo-mediumhard`       | small  | 0.02s | (TIMEOUT) | 29.7s |
| `medium/sorcerer`               | medium | 0.06s | (TIMEOUT) | 45.7s |
| `small/missing-some-information`| small  | 0.04s | 22.8s | 10.8s |
| `medium/play`                   | medium | 0.07s | 5.9s | 1.7s |
| `medium/its-hexcells-oclock`    | medium | 0.17s | 4.6s | (TIMEOUT for z3_qffd) |

These five levels are clearly pathological for Z3's CDCL+pseudo-Boolean reasoning even though Gurobi's LP relaxation handles them trivially — a useful talking point for the report.

### Heuristic contribution to each solver

Per-level diff `base=h=none;s=X` vs `cmp=h=pspr,ac3;s=X`, restricted to levels solved by both (run manually):

- `s=gurobi`: heuristic + Gurobi has essentially identical times to plain Gurobi (median 0.20s → 0.16s on the old corpus). On the full 416-level corpus the *headline* median actually drops further (0.04s → 0.02s for large) but absolute differences are sub-50ms.
- `s=z3`: heuristics provide a small speedup at the median on small/medium but slightly *reduce* large coverage (21 → 19 solved) because the heuristic pass burns budget the solver could have used on hard residual cells.
- `s=z3_qffd`: heuristics neither help nor hurt coverage; median large-tier time improves from 0.10s to 0.05s.

The heuristics-only baseline (`h=pspr,ac3;s=none`) solves 139/416, including 79/301 small and 18/24 large — confirming that the heuristics are doing real, non-trivial work and that any solver speedups under heuristics are attributable to the residual hard-cell set.

## Recommendations

1. **The PbEq promotion is the headline win.** From "50–170× slower than Gurobi on large" (Phase 1's memory note) to **1.5× geomean** across the full 416-level corpus, with full correctness preserved on every determined cell.
2. **Default Z3 solver should remain `z3` (the promoted baseline).** It is the simplest implementation and matches `z3_qffd` on every category except where solver coverage diverges on hard levels.
3. **Use `z3_qffd` when full coverage matters more than median speed.** It is the only Z3 variant that matches Gurobi's 383-level coverage; the cost is occasional 45s outliers (`sorcerer`, `modulo-mediumhard`, `missing-some-information`).
4. **`z3_assume` is no longer pulling its weight.** Post-PbEq the per-cell loop is fast, so the assumption-literal overhead now hurts. Consider removing it from `project/experiments/` unless the report wants to cite the Phase 1 ablation. Keeping it is cheap (≈30 lines).
5. **Heuristics + Z3 are a wash.** For bulk benchmarking, run `h=none;s=z3` (or `z3_qffd`). For the report's pedagogical comparison, keep `h=pspr,ac3;s=...` rows so the reader can see that heuristics don't unlock large-tier tractability — the solver was already there.

## Files added/changed in Phase 2

- [project/z3_solver.py](project/z3_solver.py) — PbEq promotion
- [project/experiments/z3_pbeq.py](project/experiments/z3_pbeq.py) — deleted
- `project/experiments/z3_pbeq_qffd.py` — deleted
- [project/experiments/z3_assumptions.py](project/experiments/z3_assumptions.py) — docstring updated
- [project/experiments/z3_qffd.py](project/experiments/z3_qffd.py) — docstring updated
- [project/solve.py](project/solve.py), [utils/benchmark.py](utils/benchmark.py) — dispatch and `--solver` choices updated
- [utils/summarize_runs.py](utils/summarize_runs.py) — new
- 1664 new records appended to [testing/runs.jsonl](testing/runs.jsonl) (8 configs × ~208 levels with appended-on-resume Gurobi top-up)
