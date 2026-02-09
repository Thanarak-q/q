#!/usr/bin/env python3
"""Preview the capybara mascot in all expressions.

Run from project root:
    python -m tools.capybara_generator
or:
    python tools/capybara_generator.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ui.mascot import render_mascot

_LABELS = {
    "default":  "Normal  — welcome screen",
    "happy":    "Happy   — flag found!  ^_^",
    "thinking": "Thinking — solving...  - -",
    "sad":      "Sad     — failed  ;_;",
}


def main() -> None:
    print()
    print("  \033[1;32m╭─ Capybara Mascot Preview ─╮\033[0m")
    print()

    for expr, label in _LABELS.items():
        print(f"  \033[1m{expr}\033[0m  {label}")
        art = render_mascot(expr)
        for line in art.split("\n"):
            print(f"    {line}")
        print()

    # Side-by-side comparison
    print("  \033[1mSide by side:\033[0m")
    all_arts = [render_mascot(e).split("\n") for e in _LABELS]
    labels = list(_LABELS.keys())
    height = max(len(a) for a in all_arts)

    # Print labels
    print("    ", end="")
    for lbl in labels:
        print(f"{lbl:^20s}", end="")
    print()

    # Print art rows
    for row in range(height):
        print("    ", end="")
        for art_lines in all_arts:
            if row < len(art_lines):
                # Pad to fixed visible width (16 chars + ANSI codes)
                line = art_lines[row]
                print(f"{line}    ", end="")
            else:
                print(" " * 20, end="")
        print()

    print()
    print("  \033[1;32m╰───────────────────────────╯\033[0m")
    print()


if __name__ == "__main__":
    main()
