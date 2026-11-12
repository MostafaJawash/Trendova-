#!/usr/bin/env python3
"""Final interleaved benchmark (Requirement 3, part 6) + report. ~1 hour for the full profile.

  py scripts/bench_final.py                 # full profile, 2 rounds, controls, cold run, freshness/browser k6, report
  py scripts/bench_final.py --quick         # 20 s profile (smoke of the machinery, NOT for the report)
  py scripts/bench_final.py --rounds 3

Variants: V0 baseline (old code, new indexes dropped) | V1 +indexes +N+1 fixes | V2 +read replica | V3 +Redis cache | V4 +ETag (final).
"""
import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ab_runner  # noqa: E402
import _stack as st  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def run(cmd):
    print('>', ' '.join(cmd), flush=True)
    r = subprocess.run(cmd, cwd=ROOT)
    if r.returncode:
        raise SystemExit(r.returncode)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--quick', action='store_true')
    ap.add_argument('--rounds', type=int, default=2)
    ap.add_argument('--prefix', default='final')
    args = ap.parse_args()
    py = sys.executable
    if subprocess.run(['docker', 'image', 'inspect', 'trendova-req3-baseline'], cwd=ROOT, capture_output=True).returncode:
        run([py, 'scripts/ab_build.py', 'baseline'])
    run(['docker', 'compose', 'up', '-d', '--build', 'app', 'db-replica', 'replica-init', 'redis'])
    run([py, 'scripts/ab_build.py', 'up'])
    st.wait_replication()
    cmd = [py, 'scripts/ab_runner.py', '--prefix', args.prefix, '--variants', 'V0,V1,V2,V3,V4', '--rounds', str(args.rounds), '--control', 'V4', '--cold', 'V4']
    if args.quick:
        cmd.append('--quick')
    run(cmd)
    # freshness (stale_reads must be 0) and the browser-like scenario (not_modified_ratio) on the final service
    ab_runner.run_k6(f'{args.prefix}_freshness', 'app', quick=args.quick, script='freshness.js')
    st.cleanup()
    run([py, 'scripts/make_report.py', '--prefix', args.prefix])


if __name__ == '__main__':
    main()
