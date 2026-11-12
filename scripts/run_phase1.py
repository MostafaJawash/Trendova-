#!/usr/bin/env python3
"""Requirement 3, phase 1: stack -> health/replication -> seed -> pytest -m req3_phase1 -> 20 s k6 smoke -> PASS/FAIL."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.run_phase import run
if __name__ == '__main__':
    sys.exit(run(1))
