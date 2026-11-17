"""Requirement 4 preflight/evidence runner. It never fabricates benchmark values."""
import argparse, subprocess, sys, time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def run(command): return subprocess.run(command,cwd=ROOT,text=True).returncode
def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--quick',action='store_true'); parser.add_argument('--from-results',action='store_true'); parser.add_argument('--no-color',action='store_true'); parser.add_argument('--pause',action='store_true'); parser.add_argument('--step',type=int); parser.add_argument('--duration',type=float)
    args=parser.parse_args(); started=time.monotonic()
    print('REQ4 DEMO - evidence only; unmeasured values are NOT MEASURED')
    if args.from_results:
        files=sorted((ROOT/'loadtest'/'results').glob('req4_latency_*.json'))
        print('SAVED RESULTS' if files else 'NOT MEASURED: no saved req4 latency result')
        for item in files: print(item.name)
        return 0
    print('STEP 0 PREFLIGHT')
    code=run(['docker','compose','ps'])
    print('Queue status:')
    queue_code=run([sys.executable,'scripts/queue_status.py'])
    print('Latency BEFORE/AFTER: NOT MEASURED')
    print('Email proof: NOT MEASURED')
    print('Worker stop/start proof: NOT MEASURED')
    print('Real-time browser proof: NOT MEASURED')
    print(f'Total runtime: {time.monotonic()-started:.2f}s')
    return 0 if code==0 and queue_code==0 else 1
if __name__=='__main__': raise SystemExit(main())
