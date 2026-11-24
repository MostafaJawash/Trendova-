"""Host-side Requirement 5 before/after proof. Uses only the Python standard library."""
import argparse
import base64
import collections
import json
import os
import subprocess
import struct
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib

PROJECT = 'trendova-req3'
# `127.0.0.1:8000` is occupied by a local Uvicorn process on this host.
# Docker Desktop publishes nginx on localhost, which is the only public door.
BASE = 'http://localhost:8000'
API = BASE + '/api/v1'
PROBLEMS = [
    ('shared uploads', 'UPLOADS_SHARED'),
    ('outbox publisher coordination', 'OUTBOX_SINGLE_PUBLISHER'),
    ('startup migration lock', 'STARTUP_LOCK_ENABLED'),
    ('Redis login limiter', 'REDIS_LOGIN_LIMITER'),
    ('worker email idempotency', 'WORKER_IDEMPOTENCY'),
]


class Reporter:
    def __init__(self, color): self.color = color
    def line(self, text, code=''):
        print((code + text + '\033[0m') if self.color and code else text, flush=True)
    def info(self, text): self.line(text, '\033[36m')
    def good(self, text): self.line(text, '\033[32m')
    def bad(self, text): self.line(text, '\033[31m')


def compose(args, env=None, timeout=240):
    command = ['docker', 'compose', '-p', PROJECT, '--profile', 'req4', '--profile', 'test'] + args
    runenv = dict(os.environ)
    if env: runenv.update(env)
    return subprocess.run(command, env=runenv, text=True, capture_output=True, timeout=timeout)


def request(url, method='GET', data=None, headers=None, timeout=12):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        # Never send local Docker traffic through OpenVPN/system HTTP proxies.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=timeout) as response:
            return response.status, dict(response.headers.items()), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers.items()), error.read()
    except Exception as error:
        return 0, {}, ('ERROR:' + type(error).__name__).encode()


def health_once():
    status, headers, _ = request(BASE + '/health')
    return status, headers.get('X-Instance', headers.get('x-instance', 'MISSING'))


def _container_health():
    result = subprocess.run(['docker', 'inspect', '-f', '{{.Name}} {{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}',
                             PROJECT + '-nginx-1', PROJECT + '-app-1', PROJECT + '-app-2', PROJECT + '-app-3'],
                            text=True, capture_output=True, timeout=20)
    return ' ; '.join(line.strip() for line in result.stdout.splitlines())


def wait_three(report, timeout=300):
    deadline = time.monotonic() + timeout
    last = ''
    next_progress = 0
    while time.monotonic() < deadline:
        rows = [health_once() for _ in range(18)]
        healthy = [instance for status, instance in rows if status == 200 and instance != 'MISSING']
        distinct = set(healthy)
        last = 'status=%s instances=%s' % (collections.Counter(s for s, _ in rows), dict(collections.Counter(healthy)))
        if len(distinct) == 3:
            report.good('READY ' + last)
            return distinct
        if time.monotonic() >= next_progress:
            report.info('WAIT containers=%s seen=%s %s' % (_container_health(), sorted(distinct), last))
            next_progress = time.monotonic() + 10
        time.sleep(5)
    raise RuntimeError('three instances were not observed: ' + last)


def recreate(toggle, value, report):
    report.info('RECREATE %s=%s' % (toggle, value))
    result = compose(['up', '-d', '--build', '--force-recreate', '--scale', 'app=3', '--scale', 'worker=3', 'app', 'worker', 'nginx'], {toggle: value})
    if result.returncode:
        raise RuntimeError('compose failed: ' + (result.stderr or result.stdout)[-1000:])
    return wait_three(report)


def restore_fixed(report):
    """Best-effort final state restoration without a header-dependent wait."""
    fixed = {toggle: 'true' for _, toggle in PROBLEMS}
    report.info('RESTORE all Req5 toggles=true')
    result = compose(['up', '-d', '--force-recreate', '--scale', 'app=3', '--scale', 'worker=3', 'app', 'worker', 'nginx'], fixed)
    if result.returncode:
        report.bad('RESTORE FAILED ' + (result.stderr or result.stdout)[-1000:])


def json_request(path, method='GET', value=None, token=None):
    headers = {'Content-Type': 'application/json'}
    if token: headers['Authorization'] = 'Bearer ' + token
    data = json.dumps(value).encode() if value is not None else None
    status, _, body = request(API + path, method, data, headers)
    try: return status, json.loads(body.decode())
    except Exception: return status, {'raw': body.decode('ascii', 'replace')[:300]}


def admin_token():
    email = os.getenv('ADMIN_EMAIL', 'admin@example.com')
    password = os.getenv('ADMIN_PASSWORD', 'ChangeMe123!')
    status, body = json_request('/auth/login', 'POST', {'email': email, 'password': password})
    if status != 200: raise RuntimeError('admin login status=%s body=%s' % (status, body))
    return body['access_token']


def multipart_product(token, category):
    boundary = 'req5demo'
    tag = 'req5_demo_' + str(int(time.time() * 1000))
    fields = {'name': tag, 'description': 'req5 demo', 'price': '1.00', 'category_id': str(category), 'initial_quantity': '1'}
    parts = []
    for name, value in fields.items():
        parts.append(('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n' % (boundary, name, value)).encode())
    def chunk(kind, payload):
        return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload) & 0xffffffff)
    # One red RGB pixel. The bytes and CRCs are built locally, not copied from
    # an unverified base64 fixture.
    png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(b'\x00\xff\x00\x00')) + chunk(b'IEND', b'')
    parts.append(('--%s\r\nContent-Disposition: form-data; name="image"; filename="req5.png"\r\nContent-Type: image/png\r\n\r\n' % boundary).encode() + png + b'\r\n')
    parts.append(('--%s--\r\n' % boundary).encode())
    status, _, body = request(API + '/products', 'POST', b''.join(parts), {'Authorization': 'Bearer ' + token, 'Content-Type': 'multipart/form-data; boundary=' + boundary})
    return status, json.loads(body.decode())


def upload_probe():
    token = admin_token()
    tag = 'req5_demo_cat_' + str(int(time.time() * 1000))
    status, category = json_request('/categories', 'POST', {'name': tag, 'description': 'req5 demo'}, token)
    if status != 201: return 'NOT REPRODUCIBLE category status=%s' % status, False
    status, product = multipart_product(token, category['id'])
    if status != 201 or not product.get('image_url'):
        return 'NOT REPRODUCIBLE upload status=%s body=%s' % (status, product), False
    seen, codes = set(), []
    for _ in range(45):
        status, headers, _ = request(BASE + product['image_url'])
        seen.add(headers.get('X-Instance', headers.get('x-instance', 'MISSING')))
        codes.append(status)
        if len(seen) == 3: break
    return 'image=%s instances=%s media_status=%s 404s=%s' % (product['image_url'], sorted(seen), dict(collections.Counter(codes)), codes.count(404)), len(seen) == 3 and codes.count(404) == 0


def limiter_probe():
    email = 'req5_demo_missing_' + str(int(time.time() * 1000)) + '@example.com'
    codes = []
    for _ in range(12):
        status, _ = json_request('/auth/login', 'POST', {'email': email, 'password': 'incorrect-password'})
        codes.append(status)
        if status == 429: break
    return 'login_statuses=%s allowed_before_429=%s' % (codes, codes.index(429) if 429 in codes else 'none'), 429 in codes


def startup_probe():
    logs = []
    for index in (1, 2, 3):
        result = subprocess.run(['docker', 'logs', PROJECT + '-app-' + str(index)], text=True, capture_output=True, timeout=20)
        logs.append(result.stdout + result.stderr)
    markers = ('duplicate', 'already exists', 'operationalerror', 'startup lock')
    count = sum(text.lower().count(marker) for text in logs for marker in markers)
    return 'startup_error_markers=%s' % count, count == 0


def queue_probe(label):
    status, _, body = request('http://127.0.0.1:8025/api/v1/messages')
    if status != 200: return 'NOT REPRODUCIBLE mailpit status=%s' % status, False
    try: count = json.loads(body.decode()).get('total', 0)
    except Exception: return 'NOT REPRODUCIBLE malformed Mailpit response', False
    return '%s mailpit_total=%s (requires order event redelivery fixture)' % (label, count), False


def probe(name):
    if name == 'shared uploads': return upload_probe()
    if name == 'Redis login limiter': return limiter_probe()
    if name == 'startup migration lock': return startup_probe()
    return queue_probe(name)


def failover(report):
    before = wait_three(report, 60)
    counts, statuses, stop = collections.Counter(), collections.Counter(), threading.Event()
    def load():
        while not stop.is_set():
            status, instance = health_once(); statuses[status] += 1; counts[instance] += 1
    thread = threading.Thread(target=load); thread.start()
    time.sleep(3)
    target = sorted(before)[0]
    # Header values are Docker container IDs; map to the container name before stopping.
    ids = subprocess.run(['docker', 'ps', '--format', '{{.ID}} {{.Names}}'], text=True, capture_output=True, timeout=20).stdout.splitlines()
    container = next((line.split()[1] for line in ids if line.split()[0].startswith(target) and '-app-' in line), PROJECT + '-app-1')
    pre_stop = dict(counts)
    stopped = subprocess.run(['docker', 'stop', container], text=True, capture_output=True, timeout=30)
    time.sleep(3); after_stop = dict(counts)
    subprocess.run(['docker', 'start', container], text=True, capture_output=True, timeout=30)
    returned = wait_three(report, 60)
    stop.set(); thread.join(timeout=15)
    stopped_hits = after_stop.get(target, 0) - pre_stop.get(target, 0)
    passed = stopped.returncode == 0 and statuses[200] > 0 and stopped_hits == 0 and target in returned
    return 'one_down statuses=%s counts=%s stopped_instance_requests=%s' % (dict(statuses), dict(counts), stopped_hits), passed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--problem', type=int, choices=range(1, len(PROBLEMS) + 1))
    parser.add_argument('--list', action='store_true')
    parser.add_argument('--skip-failover', action='store_true')
    parser.add_argument('--no-color', action='store_true')
    args = parser.parse_args()
    if args.list:
        for number, (name, toggle) in enumerate(PROBLEMS, 1): print('%s %s %s' % (number, toggle, name))
        return 0
    report = Reporter(not args.no_color and sys.stdout.isatty())
    started, rows, fail = time.monotonic(), [], None
    selected = [(args.problem, PROBLEMS[args.problem - 1])] if args.problem else list(enumerate(PROBLEMS, 1))
    try:
        for number, (name, toggle) in selected:
            recreate(toggle, 'false', report); before, before_ok = probe(name)
            recreate(toggle, 'true', report); after, after_ok = probe(name)
            # Every probe returns whether the expected fixed behavior was seen.
            # Healthy behavior in both modes means the broken variant was not
            # reproducible; only broken-before/fixed-after is a PASS.
            if before_ok and after_ok: result = 'NOT REPRODUCIBLE'
            elif not before_ok and after_ok: result = 'PASS'
            else: result = 'FAIL'
            report.line('PROBLEM %s: %s' % (number, name))
            report.line('  BEFORE (%s=false): %s' % (toggle, before))
            report.line('  AFTER  (%s=true): %s' % (toggle, after))
            report.line('  RESULT %s' % result)
            rows.append((name, before, after, result))
        if not args.skip_failover:
            detail, passed = failover(report); report.line('FAILOVER %s RESULT %s' % (detail, 'PASS' if passed else 'FAIL'))
            if not passed: fail = 'failover'
    except Exception as error:
        fail = str(error)
        report.bad('HARNESS ERROR ' + fail)
    finally:
        restore_fixed(report)
    report.line('SUMMARY Problem | BEFORE | AFTER | RESULT')
    for row in rows: report.line('%s | %s | %s | %s' % row)
    overall = 'PASS' if rows and all(row[3] == 'PASS' for row in rows) and not fail else 'FAIL'
    report.line('OVERALL %s runtime_seconds=%.1f' % (overall, time.monotonic() - started))
    return 0 if overall == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
