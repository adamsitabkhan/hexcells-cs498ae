"""Step-by-step animation of an incremental Hexcells solve.

Reuses the rendering style from `visualize.py` and adds:
  - A `Frame` snapshot dataclass capturing the puzzle's player-visible state
    at each step of the incremental solve.
  - An interactive `Animator` window with keyboard step navigation.
  - GIF export.

Cell visualization conventions:
  - Hidden cell               → orange
  - Revealed empty            → dark slate gray (with hint text in white if it has one)
  - Revealed mine             → royal blue (with hint text if it's a ZONE18)
  - Just-determined (solver)  → yellow ring outline (for one frame, before being revealed)
  - Just-determined (heuristic) → green ring outline
  - Stuck                     → light grey (final frame only, if the solver couldn't finish)

Keyboard controls:
  ← / →   step backward / forward one frame
  Home    jump to the first frame
  End     jump to the last frame
  Space   toggle auto-play
  s       save GIF (to <level>_solve.gif next to the hexcells file)
  q       close window
"""

import math
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

import matplotlib.pyplot as plt
from matplotlib.patches import RegularPolygon

from ..lib.parser import CellType, Coords, Hint, Modifier, Problem


HIDDEN_COLOR = "#E69F00"              # orange — cell not yet deduced
EMPTY_COLOR = "#2F4F4F"               # dark slate gray — revealed empty (no mine)
MINE_COLOR = "#4169E1"                # royal blue — revealed mine
HIGHLIGHT_COLOR = "#FFD700"           # yellow — just-determined by solver
HEURISTIC_HIGHLIGHT_COLOR = "#2ECC71" # green — just-determined by heuristic
STUCK_COLOR = "#A9A9A9"               # grey — cells solver couldn't determine
HIDDEN_EDGE = "#8B4513"               # dark orange edge for hidden cells


@dataclass
class Frame:
    known: Dict[Coords, bool]
    visible_hint_coords: Set[Coords]
    highlighted: Set[Coords] = field(default_factory=set)           # solver-determined
    heuristic_highlighted: Set[Coords] = field(default_factory=set) # heuristic-determined
    stuck: Set[Coords] = field(default_factory=set)
    caption: str = ""


def axial_to_pixel(q: int, r: int, size: float = 1.0):
    # Hexcells uses flat-top hexagons (the parser's grid maps straight-up
    # neighbors to the same column).
    x = size * 1.5 * q
    y = size * (math.sqrt(3.0) / 2.0) * (q + 2.0 * r)
    return x, -y


class Animator:
    def __init__(
        self,
        problem: Problem,
        frames: List[Frame],
        title_prefix: str = "",
        gif_path: Optional[str] = None,
    ):
        self.problem = problem
        self.frames = frames
        self.title_prefix = title_prefix
        self.gif_path = gif_path
        self.idx = 0
        self._playing = False
        self._timer = None

        self.hint_by_coords: Dict[Coords, Hint] = {h.coords: h for h in problem.hints}

        # Precompute cell + hint pixel positions for axes bounds
        self._positions: Dict[Coords, tuple] = {}
        for c in problem.cells:
            self._positions[c] = axial_to_pixel(c.q, c.r)
        for h in problem.hints:
            if h.coords not in self._positions:
                self._positions[h.coords] = axial_to_pixel(h.coords.q, h.coords.r)

        self.fig, self.ax = plt.subplots(figsize=(11, 11))
        self.fig.canvas.mpl_connect("key_press_event", self._on_key)
        self._render()

    def _axes_bounds(self):
        xs, ys = zip(*self._positions.values())
        pad = 2.0
        return (min(xs) - pad, max(xs) + pad, min(ys) - pad, max(ys) + pad)

    def _render(self):
        frame = self.frames[self.idx]
        self.ax.clear()
        self.ax.set_aspect("equal")
        self.ax.axis("off")
        x0, x1, y0, y1 = self._axes_bounds()
        self.ax.set_xlim(x0, x1)
        self.ax.set_ylim(y0, y1)

        for coords in self.problem.cells:
            x, y = self._positions[coords]

            if coords in frame.stuck:
                face = STUCK_COLOR
                text_color = "white"
            elif coords in frame.known:
                face = MINE_COLOR if frame.known[coords] else EMPTY_COLOR
                text_color = "white"
            else:
                face = HIDDEN_COLOR
                text_color = "white"

            if coords in frame.heuristic_highlighted:
                edge = HEURISTIC_HIGHLIGHT_COLOR
                lw = 4.0
            elif coords in frame.highlighted:
                edge = HIGHLIGHT_COLOR
                lw = 4.0
            elif coords in frame.known or coords in frame.stuck:
                edge = "black"
                lw = 1.5
            else:
                edge = HIDDEN_EDGE
                lw = 1.5

            poly = RegularPolygon(
                (x, y),
                numVertices=6,
                radius=0.95,
                orientation=math.pi / 6,
                facecolor=face,
                edgecolor=edge,
                linewidth=lw,
            )
            self.ax.add_patch(poly)

            # Hint text on revealed cells (or LINE hints — handled below)
            if coords in frame.visible_hint_coords and coords in self.hint_by_coords:
                hint = self.hint_by_coords[coords]
                if hint.type in (CellType.ZONE6, CellType.ZONE18):
                    text = self._format_hint_text(hint)
                    self.ax.text(
                        x, y, text,
                        ha="center", va="center",
                        color=text_color, fontweight="bold", fontsize=11,
                    )

        # LINE hints (external markers)
        for hint in self.problem.hints:
            if hint.type != CellType.LINE:
                continue
            if hint.coords not in frame.visible_hint_coords:
                continue
            x, y = self._positions[hint.coords]
            text = self._format_hint_text(hint)
            self.ax.text(
                x, y, text,
                ha="center", va="center",
                color="black", fontweight="bold", fontsize=9,
                bbox=dict(
                    facecolor="white", edgecolor="black",
                    boxstyle="round,pad=0.2", alpha=0.85,
                ),
                zorder=10,
            )
            if hint.scope:
                last = hint.scope[-1]
                end_x, end_y = axial_to_pixel(last.q, last.r)
                self.ax.plot(
                    [x, end_x], [y, end_y],
                    color="white", alpha=0.35, linewidth=6, zorder=1,
                )

        n_known = len(frame.known)
        n_total = len(self.problem.cells)
        title = (
            f"{self.title_prefix}"
            f"Frame {self.idx + 1}/{len(self.frames)}  •  "
            f"{n_known}/{n_total} known  •  {frame.caption}"
        )
        self.ax.set_title(title, fontsize=12)
        self.fig.canvas.draw_idle()

    @staticmethod
    def _format_hint_text(hint: Hint) -> str:
        text = str(hint.value)
        if hint.modifier == Modifier.TOGETHER:
            return "{" + text + "}"
        if hint.modifier == Modifier.SEPARATED:
            return "-" + text + "-"
        return text

    def _on_key(self, event):
        if event.key == "right":
            self.idx = min(self.idx + 1, len(self.frames) - 1)
            self._render()
        elif event.key == "left":
            self.idx = max(self.idx - 1, 0)
            self._render()
        elif event.key == "home":
            self.idx = 0
            self._render()
        elif event.key == "end":
            self.idx = len(self.frames) - 1
            self._render()
        elif event.key == " ":
            self._toggle_play()
        elif event.key == "s":
            if self.gif_path:
                self.save_gif(self.gif_path)
            else:
                print("No GIF path configured.")
        elif event.key == "q":
            plt.close(self.fig)

    def _toggle_play(self):
        if self._playing:
            self._playing = False
            if self._timer is not None:
                self._timer.stop()
                self._timer = None
        else:
            self._playing = True
            self._timer = self.fig.canvas.new_timer(interval=700)
            self._timer.add_callback(self._auto_advance)
            self._timer.start()

    def _auto_advance(self):
        if self.idx >= len(self.frames) - 1:
            self._toggle_play()
            return
        self.idx += 1
        self._render()

    def show(self):
        plt.show()

    def save_gif(self, output_path: str, fps: int = 1):
        from matplotlib.animation import FuncAnimation, PillowWriter

        original_idx = self.idx

        def update(i):
            self.idx = i
            self._render()
            return []

        anim = FuncAnimation(
            self.fig, update,
            frames=len(self.frames),
            interval=1000 // max(fps, 1),
            blit=False, repeat=False,
        )
        anim.save(output_path, writer=PillowWriter(fps=fps))
        print(f"Saved GIF to {output_path}")
        self.idx = original_idx
        self._render()
