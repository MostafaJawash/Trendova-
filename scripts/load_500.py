"""Requirement 5 HTTP distribution measurement (Python stdlib only)."""
import argparse
import collections
import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

def percentile(values, p):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * p))] if ordered else None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://localhost:8000')
    parser.add_argument('--requests', type=int, default=500)
    parser.add_argument('--concurrency', type=int, default=25)
    parser.add_argument('--output', default='docs/req5/results/load_500.json')
    args = parser.parse_args()
    instances, statuses, latencies, lock = collections.Counter(), collections.Counter(), [], threading.Lock()
    jobs = list(range(args.requests))
    def worker():
        while True:
            with lock:
                if not jobs: return
                jobs.pop()
            started = time.perf_counter()
            try:
                with urllib.request.urlopen(args.base_url.rstrip('/') + '/health', timeout=15) as response:
                    status, instance = response.status, response.headers.get('X-Instance', 'MISSING')
            except urllib.error.HTTPError as exc: status, instance = exc.code, exc.headers.get('X-Instance', 'MISSING')
            except Exception as exc: status, instance = 'ERROR', type(exc).__name__
            with lock:
                statuses[str(status)] += 1; instances[instance] += 1; latencies.append((time.perf_counter()-started)*1000)
    started = time.perf_counter()
    threads = [threading.Thread(target=worker) for _ in range(args.concurrency)]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    elapsed = time.perf_counter() - started
    out = {'requests': args.requests, 'elapsed_seconds': round(elapsed, 3), 'requests_per_second': round(args.requests/elapsed, 2), 'per_instance': dict(instances), 'status_codes': dict(statuses), 'p50_ms': round(percentile(latencies,.5),2), 'p95_ms': round(percentile(latencies,.95),2), 'p99_ms': round(percentile(latencies,.99),2), 'errors': sum(v for k,v in statuses.items() if k == 'ERROR' or not k.startswith('2'))}
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(out, indent=2), encoding='utf-8')
    print(json.dumps(out, indent=2))

if __name__ == '__main__': main()
