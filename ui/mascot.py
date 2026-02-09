"""Capybara mascot for q agent.

Rendered using Unicode half-block characters (▀ ▄ █) with ANSI 24-bit
true-color escape sequences.  Each character cell encodes two vertical
pixels (top / bottom), giving effective double vertical resolution.

Grid: 16 wide × 12 tall  →  16 chars × 6 terminal lines.

Usage::

    from ui.mascot import render_mascot, CAPYBARA, CAPYBARA_HAPPY

    # Direct print
    print(render_mascot("happy"))

    # With Rich
    from rich.text import Text
    console.print(Text.from_ansi(CAPYBARA))
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Color palette  (index → RGB tuple, or None = transparent / terminal bg)
# ---------------------------------------------------------------------------

_PALETTE: dict[int, tuple[int, int, int] | None] = {
    0: None,               # transparent
    1: (45, 138, 78),      # body green    #2d8a4e
    2: (92, 184, 92),      # light green   #5cb85c  — belly / cheeks
    3: (30, 30, 30),       # near-black    #1e1e1e  — eyes
    4: (26, 107, 53),      # dark green    #1a6b35  — nose
    5: (255, 255, 255),    # white                  — tears
}

# ---------------------------------------------------------------------------
# Pixel grid  (16 wide × 12 tall)
# ---------------------------------------------------------------------------

_BASE: list[list[int]] = [
    [0,0,0,0,1,1,0,0,0,0,1,1,0,0,0,0],  #  0  ears
    [0,0,1,1,1,1,1,1,1,1,1,1,1,1,0,0],  #  1  head top
    [0,0,1,1,1,1,1,1,1,1,1,1,1,1,0,0],  #  2  head
    [0,0,1,2,3,1,1,1,1,1,1,3,2,1,0,0],  #  3  eyes + cheeks
    [0,0,1,1,1,1,4,4,4,4,1,1,1,1,0,0],  #  4  nose
    [0,0,1,1,1,1,1,1,1,1,1,1,1,1,0,0],  #  5  mouth
    [0,0,0,1,1,1,1,1,1,1,1,1,1,0,0,0],  #  6  chin
    [0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0],  #  7  body (wider = chonky)
    [0,1,1,2,2,2,2,2,2,2,2,2,2,1,1,0],  #  8  belly
    [0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0],  #  9  body bottom
    [0,0,1,1,0,1,1,0,0,1,1,0,1,1,0,0],  # 10  four little feet
    [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],  # 11  (padding)
]

# Expression overrides — only the rows that differ from _BASE.
_EXPRESSIONS: dict[str, dict[int, list[int]]] = {
    "default": {},
    "happy": {
        # ^_^  closed eyes match cheek color
        3: [0,0,1,2,2,1,1,1,1,1,1,2,2,1,0,0],
    },
    "thinking": {
        # - -  squinting / half-closed (dark green eyes)
        3: [0,0,1,2,4,1,1,1,1,1,1,4,2,1,0,0],
    },
    "sad": {
        # ;_;  lost blush + tear drops
        3: [0,0,1,1,3,1,1,1,1,1,1,3,1,1,0,0],
        5: [0,0,1,1,5,1,1,1,1,1,1,5,1,1,0,0],
    },
}

# ---------------------------------------------------------------------------
# Grid helpers
# ---------------------------------------------------------------------------

def _make_grid(expression: str = "default") -> list[list[int]]:
    """Return a copy of _BASE with expression overrides applied."""
    grid = [row[:] for row in _BASE]
    for idx, row in _EXPRESSIONS.get(expression, {}).items():
        grid[idx] = row[:]
    return grid


def _render_grid(
    grid: list[list[int]],
    palette: dict[int, tuple[int, int, int] | None] | None = None,
) -> str:
    """Convert a pixel grid to ANSI true-color half-block art.

    Every pair of rows becomes one terminal line.  Uses ▀ (U+2580)
    with fg = top pixel and bg = bottom pixel to pack two pixels per
    character cell.
    """
    if palette is None:
        palette = _PALETTE

    lines: list[str] = []

    for y in range(0, len(grid), 2):
        top_row = grid[y]
        bot_row = grid[y + 1] if y + 1 < len(grid) else [0] * len(top_row)

        # Build (escape_sequence | None, character) per column
        cells: list[tuple[str | None, str]] = []
        for x in range(len(top_row)):
            tc = palette.get(top_row[x])
            bc = palette.get(bot_row[x])

            if tc is None and bc is None:
                cells.append((None, " "))
            elif tc is None:
                cells.append((
                    f"\033[38;2;{bc[0]};{bc[1]};{bc[2]}m", "▄",
                ))
            elif bc is None:
                cells.append((
                    f"\033[38;2;{tc[0]};{tc[1]};{tc[2]}m", "▀",
                ))
            elif tc == bc:
                cells.append((
                    f"\033[38;2;{tc[0]};{tc[1]};{tc[2]}m", "█",
                ))
            else:
                cells.append((
                    f"\033[38;2;{tc[0]};{tc[1]};{tc[2]};"
                    f"48;2;{bc[0]};{bc[1]};{bc[2]}m",
                    "▀",
                ))

        # Collapse consecutive identical sequences to reduce bytes
        parts: list[str] = []
        cur_seq: str | None = None
        active = False          # whether an ANSI sequence is currently open

        for seq, ch in cells:
            if seq != cur_seq:
                if active:
                    parts.append("\033[0m")
                    active = False
                if seq is not None:
                    parts.append(seq)
                    active = True
                cur_seq = seq
            parts.append(ch)

        if active:
            parts.append("\033[0m")

        lines.append("".join(parts))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def render_mascot(expression: str = "default") -> str:
    """Render the capybara mascot with ANSI colors.

    *expression* is one of ``"default"``, ``"happy"``, ``"thinking"``,
    ``"sad"``.

    Returns a multi-line string with embedded ANSI escape codes.
    """
    return _render_grid(_make_grid(expression))


# Pre-rendered constants (generated once at import time).
CAPYBARA: str          = render_mascot("default")
CAPYBARA_HAPPY: str    = render_mascot("happy")
CAPYBARA_THINKING: str = render_mascot("thinking")
CAPYBARA_SAD: str      = render_mascot("sad")
