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
        if not self.quiet:
            print(self.dim(msg))

    def success(self, msg: str) -> None:
        if not self.quiet:
            print(self.green(msg))

    def warning(self, msg: str) -> None:
        if not self.quiet:
            print(self.yellow(f"Warning: {msg}"))

    def error(self, msg: str) -> None:
        print(self.red(f"Error: {msg}"), file=sys.stderr)

    def header(self, title: str) -> None:
        if self.quiet:
            return
        print(self.bold(title))
        print(self.dim("-" * min(len(title), self.width())))

    def table(self, headers: Sequence[str], rows: Sequence[Sequence[str]]) -> None:
        if self.quiet:
            return
        cols = list(headers)
        data = [list(map(str, r)) for r in rows]
        widths = [len(c) for c in cols]
        for row in data:
            for i, cell in enumerate(row):
                if i < len(widths):
                    widths[i] = max(widths[i], len(cell))
        fmt = "  ".join("{:" + str(w) + "}" for w in widths)
        print(self.bold(fmt.format(*cols)))
        for row in data:
            while len(row) < len(cols):
                row.append("")
            print(fmt.format(*row[: len(cols)]))


    def status_line(self, ok: bool, name: str, detail: str = "") -> None:
        """Print a single check result line: [OK]/[X] name detail."""
        if self.quiet:
            return
        mark = self.ok("OK") if ok else self.fail("X")
        detail_s = f"  {detail}" if detail else ""
        print(f"{mark} {name}{detail_s}")

    @staticmethod
    def format_bytes(n: int) -> str:
        units = ["B", "KB", "MB", "GB"]
        f = float(max(0, n))
        for u in units:
            if f < 1024.0 or u == units[-1]:
                if u == "B":
                    return f"{int(f)} {u}"
                return f"{f:.1f} {u}"
            f /= 1024.0
        return f"{n} B"

    def progress_bar(
        self,
        received: int,
        total: int | None = None,
        *,
        prefix: str = "Downloading",
        width: int | None = None,
    ) -> None:
        """Render a single-line progress bar to stderr (TTY)."""
        if self.quiet:
            return
        if not sys.stderr.isatty():
            return

        cols = width or max(20, min(40, self.width() - 42))
        if total and total > 0:
            ratio = min(1.0, max(0.0, received / float(total)))
            filled = int(cols * ratio)
            bar = "#" * filled + "-" * (cols - filled)
            pct = int(ratio * 100)
            msg = (
                f"\r{prefix}: [{bar}] {pct:3d}%  "
                f"{self.format_bytes(received)}/{self.format_bytes(total)}"
            )
        else:
            msg = f"\r{prefix}: {self.format_bytes(received)}"
        print(msg, end="", file=sys.stderr, flush=True)
        if total and received >= total:
            print(file=sys.stderr)

    def progress_done(self) -> None:
        if self.quiet:
            return
        if sys.stderr.isatty():
            print(file=sys.stderr)
