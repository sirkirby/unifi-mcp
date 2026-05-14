"""Pytest config for skills tests — adds repo root to sys.path."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
