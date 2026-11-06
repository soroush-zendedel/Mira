"""Entry point: python -m mira / PyInstaller."""

import sys

from mira.cli import main

if __name__ == "__main__":
    # Required for some frozen Windows builds (multiprocessing safety)
    if getattr(sys, "frozen", False):
        try:
            import multiprocessing
            multiprocessing.freeze_support()
        except Exception:
            pass
    raise SystemExit(main())
