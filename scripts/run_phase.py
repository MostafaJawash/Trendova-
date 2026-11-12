#!/usr/bin/env python3
"""One-command runner for a Requirement 3 phase (used by run_phase1.py / run_phase2.py).

stack up -> wait for health + replication -> seed if empty -> pytest markers -> 20 s k6 smoke -> PASS/FAIL per check.
Exit code 0 only if every check passed.
"""
import sys
import time
from scripts import _stack as st  # noqa: E402  (importable when run as `py scripts/run_phase1.py`: see sys.path tweak below)


def run(phase):
    t0 = time.time()
    results = []

    def check(name, ok, detail=''):
        results.append((name, ok, detail))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f'  ({detail})' if detail else ''), flush=True)

    print(f'=== Requirement 3 / phase {phase} ===')
    check('stack up (app, db, replica, redis)', st.start_stack())
    st_ = st.replica_status()
    check('replication running (IO + SQL threads)', st_.get('Replica_IO_Running') == 'Yes' and st_.get('Replica_SQL_Running') == 'Yes',
          f"lag={st_.get('Seconds_Behind_Source')}s")
    check('seed present', st.seed_if_empty())
    c = st.row_counts()
    check('realistic data volume', c.get('products', 0) >= 20000 and c.get('orders', 0) >= 300000, str(c))
    markers = f'req3_phase{phase}' if phase == 1 else 'req3_phase1 or req3_phase2'
    marker_only = f'req3_phase{phase}'
    rc, summary, out = st.run_tests(marker_only)
    check(f'pytest -m {marker_only}', rc == 0, summary)
    if rc != 0:
        print(out[-3000:])
    ok, data = st.k6_smoke(f'smoke_phase{phase}')
    detail = ''
    if data:
        e = data['endpoints'].get('mixed_total', {})
        detail = f"mixed: {e.get('req_per_s')} req/s p95={e.get('p95_ms', 0):.0f} ms errors={e.get('error_rate')}"
    check('k6 smoke (20 s, 0 errors)', ok, detail)
    st.cleanup()
    failed = [n for n, ok_, _ in results if not ok_]
    print(f"=== phase {phase}: {'PASS' if not failed else 'FAIL: ' + ', '.join(failed)}  ({time.time() - t0:.0f} s) ===")
    return 0 if not failed else 1
