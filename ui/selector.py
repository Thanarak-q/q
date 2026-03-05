"""Inline arrow-key selector for terminal menus.

Provides a lightweight interactive menu that the user navigates with
arrow keys (or j/k) and confirms with Enter.  Works directly with
the terminal via ANSI escapes — no curses dependency.
"""

from __future__ import annotations

import sys
import termios
import tty


def _read_key() -> str:
    """Read a single keypress, handling arrow-key escape sequences."""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            ch2 = sys.stdin.read(1)
            if ch2 == "[":
                ch3 = sys.stdin.read(1)
                return "\x1b[" + ch3
            return "\x1b"
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def interactive_select(
    title: str,
    options: list[tuple[str, str]],
    current: str | None = None,
) -> str | None:
    """Show an inline selector navigated with arrow keys.

    Args:
        title: Header text shown above the options.
        options: List of ``(value, display_label)`` tuples.
        current: Value to pre-select and mark as "(current)".

    Returns:
        The selected *value*, or ``None`` if the user cancelled.
    """
    if not options or not sys.stdin.isatty():
        return None

    idx = 0
    for i, (val, _) in enumerate(options):
        if val == current:
            idx = i
            break

    # total lines = blank + title + each option
    total = len(options) + 2

    def _draw(sel: int, first: bool = False) -> None:
        out = sys.stdout
        if not first:
            out.write(f"\033[{total}A")  # move cursor up to redraw
        out.write("\033[2K\n")  # blank line
        out.write(f"\033[2K  \033[1m{title}\033[0m\n")
        for i, (val, label) in enumerate(options):
            out.write("\033[2K")  # clear line
            if i == sel:
                tag = "  \033[2m(current)\033[0m" if val == current else ""
                out.write(f"  \033[36m>\033[0m \033[1m{label}\033[0m{tag}\n")
            else:
                out.write(f"    \033[2m{label}\033[0m\n")
        out.flush()

    sys.stdout.flush()
    _draw(idx, first=True)

    try:
        while True:
            key = _read_key()
            if key in ("\x1b[A", "k"):  # Up / k
                idx = (idx - 1) % len(options)
                _draw(idx)
            elif key in ("\x1b[B", "j"):  # Down / j
                idx = (idx + 1) % len(options)
                _draw(idx)
            elif key in ("\r", "\n"):  # Enter
                return options[idx][0]
            elif key in ("\x1b", "\x03", "\x04"):  # Esc, Ctrl+C, Ctrl+D
                return None
    except (KeyboardInterrupt, EOFError):
        return None
    finally:
        sys.stdout.write("\n")
        sys.stdout.flush()
