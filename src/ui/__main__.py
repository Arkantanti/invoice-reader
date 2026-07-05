"""Launcher: ``python src/ui/__main__.py`` (or ``python -m ui`` from ``src/``).

Adds the ``src`` directory to ``sys.path`` — mirroring how ``src/main.py`` is run
as a script — so the sibling top-level packages (``pipeline``, ``models``) import
cleanly regardless of the current working directory.
"""
import os
import sys

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from ui.app import main

if __name__ == "__main__":
    main()
