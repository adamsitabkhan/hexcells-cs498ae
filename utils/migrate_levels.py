"""Migrate the levels/ directory from hash-named flat files to a two-tier
category + named-subdirectory layout:

    levels/
      small/           (< SMALL_THRESHOLD cells)
        pick-up-sticks/
          level.hexcells
          thumbnail.png
          solve.gif      (if one exists)
      medium/           (SMALL_THRESHOLD – LARGE_THRESHOLD cells)
        ...
      large/            (>= LARGE_THRESHOLD cells)
        ...
      index.json        (hash → {slug, category, name, author, cells})

Run without --execute to preview every action (dry-run).
Run with --execute to apply the changes.
"""

import argparse
import html
import json
import os
import re
import shutil
import sys

from project.lib.parser import Problem, parse_hexcells

# ── Thresholds (cells) ────────────────────────────────────────────────────────
# The parser rejects some levels (non-standard grid width, bad alignment).
# For those we fall back to counting non-empty cell tokens directly from the
# raw grid bytes — good enough to categorize by size.
SMALL_THRESHOLD = 100   # < 100 → small
LARGE_THRESHOLD = 300   # >= 300 → large; else medium

LEVELS_DIR = "levels"


# ── Helpers ───────────────────────────────────────────────────────────────────

def count_cells_raw(path: str) -> int:
    """Estimate cell count by scanning grid rows for non-empty cell tokens.
    Used as a fallback when the parser rejects a level file."""
    EMPTY = ".."
    count = 0
    with open(path) as f:
        lines = f.readlines()
    grid_lines = lines[5:38]          # same slice the parser uses
    for line in grid_lines:
        line = line.rstrip("\r\n")
        step = 2
        for i in range(0, len(line) - 1, step):
            pair = line[i:i + 2]
            if pair != EMPTY and pair.strip():
                count += 1
    return count

def slugify(text: str) -> str:
    text = html.unescape(text)
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)   # strip punctuation except hyphen
    text = re.sub(r"[\s_]+", "-", text)    # spaces/underscores → hyphen
    text = re.sub(r"-{2,}", "-", text)     # collapse runs of hyphens
    return text.strip("-")


def category(cell_count: int) -> str:
    if cell_count < SMALL_THRESHOLD:
        return "small"
    if cell_count < LARGE_THRESHOLD:
        return "medium"
    return "large"


def unique_slug(slug: str, taken: set, author_slug: str) -> str:
    """Return a slug that isn't in `taken`, disambiguating with author then index."""
    if slug not in taken:
        return slug
    candidate = f"{slug}-by-{author_slug}"
    if candidate not in taken:
        return candidate
    i = 2
    while True:
        candidate = f"{slug}-{i}"
        if candidate not in taken:
            return candidate
        i += 1


# ── Main ──────────────────────────────────────────────────────────────────────

def collect_levels():
    """Return a list of dicts, one per .hexcells file found in LEVELS_DIR."""
    entries = []
    for fname in sorted(os.listdir(LEVELS_DIR)):
        if not fname.endswith(".hexcells"):
            continue
        hash_id = fname[: -len(".hexcells")]
        path = os.path.join(LEVELS_DIR, fname)

        with open(path) as f:
            lines = f.readlines()
        name = html.unescape(lines[1].strip()) if len(lines) > 1 else hash_id
        author = html.unescape(lines[2].strip()) if len(lines) > 2 else "unknown"

        parse_note = ""
        try:
            level = parse_hexcells(path)
            cells = len(Problem(level).cells)
        except Exception as exc:
            cells = count_cells_raw(path)
            parse_note = f" [parser error: {exc}; raw cell estimate used]"

        if parse_note:
            print(f"  NOTE {fname}: {parse_note.strip()}", file=sys.stderr)

        entries.append({
            "hash": hash_id,
            "name": name,
            "author": author,
            "cells": cells,
            "parse_note": parse_note.strip(),
        })
    return entries


def plan(entries):
    """Assign a (category, slug, dest_dir) to each entry, resolving collisions."""
    taken_by_cat: dict[str, set] = {"small": set(), "medium": set(), "large": set()}
    planned = []

    for e in entries:
        cat = category(e["cells"])
        base_slug = slugify(e["name"]) or e["hash"][:8]
        author_slug = slugify(e["author"]) or e["hash"][:8]
        slug = unique_slug(base_slug, taken_by_cat[cat], author_slug)
        taken_by_cat[cat].add(slug)
        dest = os.path.join(LEVELS_DIR, cat, slug)
        planned.append({**e, "category": cat, "slug": slug, "dest": dest})

    return planned


def build_file_map(entry):
    """Return list of (src, dst) file moves for one level entry."""
    h = entry["hash"]
    d = entry["dest"]
    moves = []

    src_hexcells = os.path.join(LEVELS_DIR, f"{h}.hexcells")
    if os.path.exists(src_hexcells):
        moves.append((src_hexcells, os.path.join(d, "level.hexcells")))

    src_png = os.path.join(LEVELS_DIR, f"{h}.png")
    if os.path.exists(src_png):
        moves.append((src_png, os.path.join(d, "thumbnail.png")))

    src_gif = os.path.join(LEVELS_DIR, f"{h}_solve.gif")
    if os.path.exists(src_gif):
        moves.append((src_gif, os.path.join(d, "solve.gif")))

    return moves


def run(execute: bool):
    print(f"Scanning {LEVELS_DIR}/ ...\n")
    entries = collect_levels()
    print(f"Found {len(entries)} levels.\n")

    planned = plan(entries)

    # Preview / execute file moves
    total_moves = 0
    for entry in planned:
        moves = build_file_map(entry)
        if not moves:
            continue
        label = f"[{entry['category']:6}]  {entry['name']} ({entry['cells']} cells)"
        print(f"  {label}")
        print(f"    → {entry['dest']}/")
        for src, dst in moves:
            print(f"      {os.path.basename(src)} → {os.path.basename(dst)}")
            if execute:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.move(src, dst)
        total_moves += len(moves)

    print(f"\n{total_moves} files {'moved' if execute else 'would be moved'} across "
          f"{len(planned)} level directories.")

    # Write index.json
    index = {}
    for e in planned:
        entry = {
            "name": e["name"],
            "author": e["author"],
            "cells": e["cells"],
            "category": e["category"],
            "slug": e["slug"],
            "path": os.path.join(e["category"], e["slug"]),
        }
        if e.get("parse_note"):
            entry["parse_note"] = e["parse_note"]
        index[e["hash"]] = entry
    index_path = os.path.join(LEVELS_DIR, "index.json")
    if execute:
        with open(index_path, "w") as f:
            json.dump(index, f, indent=2, ensure_ascii=False)
        print(f"Wrote {index_path}  ({len(index)} entries)")
    else:
        print(f"\nWould write {index_path}  ({len(index)} entries)")
        print("(Re-run with --execute to apply.)")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--execute", action="store_true",
                   help="Apply the migration. Omit for a dry-run preview.")
    p.add_argument("--small-threshold", type=int, default=SMALL_THRESHOLD,
                   metavar="N", help=f"Max cells for 'small' (default {SMALL_THRESHOLD})")
    p.add_argument("--large-threshold", type=int, default=LARGE_THRESHOLD,
                   metavar="N", help=f"Min cells for 'large' (default {LARGE_THRESHOLD})")
    args = p.parse_args()

    SMALL_THRESHOLD = args.small_threshold
    LARGE_THRESHOLD = args.large_threshold

    run(execute=args.execute)
