"""Move levels from levels/generated/ into levels/small|medium|large/.

Uses the same thresholds as migrate_levels.py:
  < 100 cells  → small
  < 300 cells  → medium
  >= 300 cells → large

Cell counts are read from levels/generated/index.jsonl. Levels not in the
index are skipped with a warning. Slug collisions in the destination are
resolved by appending -gen, then -gen2, -gen3, ...

Run:
    python utils/sort_generated.py [--dry-run] [--execute]
"""

import argparse
import json
import os
import shutil
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SMALL_THRESHOLD = 100
LARGE_THRESHOLD = 300


def category(cells: int) -> str:
    if cells < SMALL_THRESHOLD:
        return "small"
    if cells < LARGE_THRESHOLD:
        return "medium"
    return "large"


def unique_dest(dest_cat_dir: str, slug: str) -> str:
    """Return a slug that doesn't collide in dest_cat_dir."""
    candidate = slug
    suffix = 0
    while os.path.exists(os.path.join(dest_cat_dir, candidate)):
        suffix += 1
        candidate = f"{slug}-gen{'' if suffix == 1 else suffix}"
    return candidate


def main():
    p = argparse.ArgumentParser(
        prog="python utils/sort_generated.py",
        description="Sort levels/generated/ into small/medium/large.",
    )
    p.add_argument("--dry-run", action="store_true", default=True,
                   help="Print planned moves without executing (default).")
    p.add_argument("--execute", action="store_true",
                   help="Actually move the directories.")
    args = p.parse_args()
    execute = args.execute

    gen_dir = os.path.join(_REPO_ROOT, "levels", "generated")
    index_path = os.path.join(gen_dir, "index.jsonl")

    if not os.path.exists(index_path):
        print(f"No index found at {index_path}")
        sys.exit(1)

    # Build slug → cells map from index
    slug_to_cells: dict[str, int] = {}
    with open(index_path) as f:
        for line in f:
            rec = json.loads(line)
            slug = rec["slug"]
            slug_to_cells[slug] = rec["cells"]

    # Collect all level subdirs in generated/
    entries = sorted(
        e for e in os.listdir(gen_dir)
        if os.path.isdir(os.path.join(gen_dir, e)) and e != "__pycache__"
    )

    moves = []   # (src_dir, dest_dir, slug)
    skipped = []

    for slug in entries:
        if slug not in slug_to_cells:
            # Fall back to parsing the level file directly
            level_file = os.path.join(gen_dir, slug, "level.hexcells")
            if not os.path.exists(level_file):
                skipped.append(slug)
                continue
            try:
                sys.path.insert(0, _REPO_ROOT)
                from project.lib.parser import Problem, parse_hexcells
                problem = Problem(parse_hexcells(level_file))
                slug_to_cells[slug] = len(problem.cells)
            except Exception:
                skipped.append(slug)
                continue

        cells = slug_to_cells[slug]
        cat = category(cells)
        dest_cat_dir = os.path.join(_REPO_ROOT, "levels", cat)
        dest_slug = unique_dest(dest_cat_dir, slug)
        src = os.path.join(gen_dir, slug)
        dst = os.path.join(dest_cat_dir, dest_slug)
        moves.append((src, dst, cat, cells))

    # Report
    from collections import Counter
    cat_counts = Counter(cat for _, _, cat, _ in moves)
    print(f"Planned moves: {len(moves)} levels  "
          f"(small={cat_counts['small']}, medium={cat_counts['medium']}, large={cat_counts['large']})")
    if skipped:
        print(f"Skipped (not in index): {skipped}")

    if not execute:
        print("\n[dry-run] pass --execute to apply\n")
        for src, dst, cat, cells in moves:
            slug = os.path.basename(src)
            dest_slug = os.path.basename(dst)
            rename = f" → {dest_slug}" if dest_slug != slug else ""
            print(f"  {cat:6s}  {cells:>3} cells  {slug}{rename}")
        return

    # Execute moves
    moved = 0
    for src, dst, cat, cells in moves:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)
        moved += 1

    # Remove leftover files in generated/ (index.jsonl stays for reference)
    print(f"Moved {moved} level directories.")

    remaining = [
        e for e in os.listdir(gen_dir)
        if os.path.isdir(os.path.join(gen_dir, e))
    ]
    if not remaining:
        print("levels/generated/ is now empty of subdirectories.")


if __name__ == "__main__":
    main()
