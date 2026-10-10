"""Pytest configuration ensuring project root is in sys.path."""

from pathlib import Path
import sys

# Ensure repository root is in sys.path
root_dir = str(Path(__file__).resolve().parent.parent)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)
