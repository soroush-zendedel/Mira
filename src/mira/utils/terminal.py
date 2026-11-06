"""Simple terminal rendering with optional ANSI colors."""

from __future__ import annotations

import os
import shutil
import sys
from typing import Optional, Sequence


class Terminal:
    """Lightweight terminal helper. Falls back to plain text when needed."""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    def __init__(self, use_color: Optional[bool] = None, quiet: bool = False, verbose: bool = False):
        self.quiet = quiet
        self.verbose = verbose
        if use_color is None:
            use_color = self._detect_color()
        self.use_color = use_color and not quiet

    @staticmethod
    def _detect_color() -> bool:
        if os.environ.get("NO_COLOR"):
            return False
        if os.environ.get("FORCE_COLOR"):
            return True
        if not sys.stdout.isatty():
            return False
        return True

    def width(self) -> int:
        try:
            return shutil.get_terminal_size(fallback=(80, 24)).columns
        except Exception:
            return 80

    def _c(self, code: str, text: str) -> str:
        if not self.use_color:
            return text
        return f"{code}{text}{self.RESET}"

    def bold(self, text: str) -> str:
        return self._c(self.BOLD, text)

    def green(self, text: str) -> str:
        return self._c(self.GREEN, text)

    def red(self, text: str) -> str:
        return self._c(self.RED, text)

    def yellow(self, text: str) -> str:
        return self._c(self.YELLOW, text)

    def cyan(self, text: str) -> str:
        return self._c(self.CYAN, text)

    def dim(self, text: str) -> str:
        return self._c(self.DIM, text)

    def ok(self, text: str = "OK") -> str:
        return self.green(f"[{text}]")

    def fail(self, text: str = "X") -> str:
        return self.red(f"[{text}]")

    def warn_mark(self, text: str = "!") -> str:
        return self.yellow(f"[{text}]")

    def print(self, *args, **kwargs) -> None:
        if not self.quiet:
            print(*args, **kwargs)

    def info(self, msg: str) -> None:
        self.print(msg)

    def success(self, msg: str) -> None:
        self.print(self.green(msg))

    def warning(self, msg: str) -> None:
        self.print(self.yellow(f"Warning: {msg}"))

    def error(self, msg: str) -> None:
        print(self.red(f"Error: {msg}"), file=sys.stderr)

    def header(self, title: str) -> None:
        self.print()
        self.print(self.bold(title))
        self.print(self.dim("-" * min(len(title), self.width())))

    def table(self, headers: Sequence[str], rows: Sequence[Sequence[str]], min_widths: Optional[list[int]] = None) -> None:
        if not rows and not headers:
            return
        cols = len(headers)
        widths = [len(h) for h in headers]
        if min_widths:
            widths = [max(w, m) for w, m in zip(widths, min_widths)]
        for row in rows:
            for i, cell in enumerate(row):
                if i < cols:
                    widths[i] = max(widths[i], len(str(cell)))
        # header
        line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
        self.print(self.bold(line))
        for row in rows:
            cells = [str(row[i]).ljust(widths[i]) if i < len(row) else "" for i in range(cols)]
            self.print("  ".join(cells))

    def status_line(self, ok: bool, name: str, detail: str = "") -> None:
        mark = self.ok() if ok else self.fail()
        line = f"  {mark}  {name}"
        if detail:
            line += f"  {self.dim(detail)}"
        self.print(line)


# Global default instance (can be replaced by CLI)
term = Terminal()