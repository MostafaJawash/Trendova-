#!/usr/bin/env python3
"""Measure the replica lag under write load (Requirement 3, part 3.5). Stdlib only.

Two loads against the final app (port 8000):
  1. `k6_create_order`: the fixed k6 create_order scenario (open loop, 5 orders/s) - the load the RYW window must exceed;
  2. `burst`: 8 closed-loop buyers creating orders as fast as possible (a stress case well above the k6 rate).
Lag is sampled about twice per second from `SHOW REPLICA STATUS` (Seconds_Behind_Source) while the load runs.
Writes loadtest/results/replica_lag.json. Throw-away data is named req3_test_lag_* and removed at the end.

  py scripts/measure_lag.py [--seconds 30]
"""
import argparse
import json
import statistics
import sys
import threading
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _stack as st  # noqa: E402
import ab_runner as abr  # noqa: E402
import demo_req3 as dm  # noqa: E402  (reuses its small HTTP helpers)


def sampler(stop, out):
    while not stop.is_set():
        s = st.replica_status().get('Seconds_Behind_Source')
        out.append(int(s) if s and s.isdigit() else None)


def summarize(samples):
    v = [x for x in samples if x is not None]
    return {'samples': len(samples), 'unknown_samples': len(samples) - len(v), 'max_s': max(v) if v else None,
            'mean_s': round(statistics.mean(v), 2) if v else None, 'nonzero_samples': sum(1 for x in v if x > 0)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seconds', type=int, default=30)
    args = ap.parse_args()
    out = {'generated_at': time.strftime('%Y-%m-%d %H:%M:%S')}
    # 1. fixed k6 profile
    samples, stop = [], threading.Event()
    t = threading.Thread(target=sampler, args=(stop, samples), daemon=True)
    t.start()
    data = abr.run_k6('replica_lag_k6_create_order', 'app', only='create_order', quick=False)
    stop.set(); t.join(timeout=10)
    e = data['endpoints']['create_order']
    out['k6_create_order'] = {**summarize(samples), 'orders_per_s': e['req_per_s'], 'errors': e['error_rate']}
    print('k6 create_order (5/s):', out['k6_create_order'], flush=True)
    time.sleep(3)
    # 2. saturating burst
    tag = 'req3_test_lag_' + uuid.uuid4().hex[:6]
    admin = dm.login(8000, *dm.ADMIN)
    cat = dm.call(8000, 'POST', '/categories', admin, js={'name': tag, 'description': 'lag'}).json()['id']
    pid = dm.call(8000, 'POST', '/products', admin, form={'name': tag, 'description': 'lag', 'price': '1.00', 'category_id': str(cat), 'initial_quantity': '1000000'}).json()['id']
    tokens = []
    for i in range(8):
        email = f'{tag}_{i}@example.com'
        dm.call(8000, 'POST', '/auth/register', js={'email': email, 'name': 'lag', 'password': 'password123'})
        tokens.append(dm.login(8000, email, 'password123'))
    samples, stop, done = [], threading.Event(), []
    t = threading.Thread(target=sampler, args=(stop, samples), daemon=True)
    t.start()
    end = time.time() + args.seconds

    def buyer(tok):
        n = 0
        while time.time() < end:
            if dm.call(8000, 'POST', '/orders', tok, js={'items': [{'product_id': pid, 'quantity': 1}]}).status == 201:
                n += 1
        done.append(n)
    ths = [threading.Thread(target=buyer, args=(tk,)) for tk in tokens]
    [x.start() for x in ths]; [x.join() for x in ths]
    drain0 = time.time()
    while True:   # time until the replica has caught up after the burst ends
        s = st.replica_status()
        if s.get('Seconds_Behind_Source') == '0' and 'read all relay log' in s.get('Replica_SQL_Running_State', ''):
            break
        time.sleep(0.3)
    drain = time.time() - drain0
    stop.set(); t.join(timeout=10)
    out['burst'] = {**summarize(samples), 'orders': sum(done), 'orders_per_s': round(sum(done) / args.seconds, 1), 'seconds_to_catch_up_after_stop': round(drain, 1)}
    print('burst (8 buyers, max rate):', out['burst'], flush=True)
    st.cleanup()
    (st.RESULTS / 'replica_lag.json').write_text(json.dumps(out, indent=1))
    worst = max(v for v in (out['k6_create_order']['max_s'], out['burst']['max_s']) if v is not None)
    print(f'max lag observed: {worst} s  ->  RYW_WINDOW_SECONDS must exceed this (current default 5)')


if __name__ == '__main__':
    main()
