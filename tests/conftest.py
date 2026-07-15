"""
tests/conftest.py

Ensures the repo root is on sys.path so tests can import `apps`, `library`,
and `ui` packages regardless of how pytest is invoked.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
