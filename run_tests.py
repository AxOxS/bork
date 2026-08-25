#!/usr/bin/env python3
"""Run the test suite: `python3 run_tests.py [-v]`."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

if __name__ == "__main__":
    verbosity = 2 if "-v" in sys.argv else 1
    suite = unittest.defaultTestLoader.discover(os.path.join(ROOT, "tests"), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=verbosity).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
