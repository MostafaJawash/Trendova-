"""Small, safe Requirement 5 evidence reader/runner (Python stdlib only)."""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

RESULT = Path('docs/req5/results/load_500.json')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--quick', action='store_true')
    parser.add_argument('--from-results', action='store_true')
    parser.add_argument('--no-color', action='store_true')
    parser.add_argument('--step', type=int)
    args = parser.parse_args()
    started = time.monotonic()
    print('REQ5 DEMO: nginx topology and distribution')
    if args.from_results:
        if RESULT.exists(): print('SAVED RESULTS\n' + RESULT.read_text(encoding='utf-8'))
        else: print('SAVED RESULTS: NOT MEASURED')
        return
    command = [sys.executable, 'scripts/load_500.py']
    if args.quick: command += ['--requests', '50', '--output', 'docs/req5/results/load_50.json']
    result = subprocess.run(command, text=True)
    print('RESULT ' + ('PASS' if result.returncode == 0 else 'FAIL'))
    print('runtime_seconds=%.2f' % (time.monotonic() - started))
    raise SystemExit(result.returncode)

if __name__ == '__main__': main()
