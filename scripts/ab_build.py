#!/usr/bin/env python3
"""Build / start the A/B containers used by scripts/ab_runner.py and scripts/demo_req3.py. Stdlib only.

  py scripts/ab_build.py baseline   # build image `trendova-req3-baseline` from the last commit BEFORE any Req 3 change
  py scripts/ab_build.py prev       # tag the currently built app image as `trendova-req3-prev` and (re)start app-prev
  py scripts/ab_build.py up         # start app-v0..app-v3 (+ app-prev if its image exists)
  py scripts/ab_build.py down       # stop the A/B containers

The baseline source is exported with `git archive` into .ab/baseline (git-ignored): the working tree, the index
and every branch are never touched.
"""
import io
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AB = ROOT / '.ab' / 'baseline'
MARKER_FILE = 'app/core/query_counter.py'   # first file added by the Req 3 work


def run(cmd, **kw):
    return subprocess.run(cmd, cwd=ROOT, check=True, **kw)


def baseline_commit():
    """Parent of the commit that introduced the first Req 3 file = last commit BEFORE any Req 3 change."""
    first = subprocess.run(['git', 'log', '--diff-filter=A', '--format=%H', '--', MARKER_FILE], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    if not first:
        raise SystemExit(f'cannot find the commit that added {MARKER_FILE}')
    return subprocess.run(['git', 'rev-parse', first[-1] + '^'], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def baseline():
    commit = baseline_commit()
    if AB.exists():
        shutil.rmtree(AB)
    AB.mkdir(parents=True)
    tar = subprocess.run(['git', 'archive', '--format=tar', commit], cwd=ROOT, capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(tar)) as t:
        t.extractall(AB)
    run(['docker', 'build', '-q', '-t', 'trendova-req3-baseline', str(AB)])
    (AB / 'COMMIT').write_text(commit)
    print(f'baseline image built from commit {commit}')


def prev():
    run(['docker', 'tag', 'trendova-req3-app', 'trendova-req3-prev'])
    run(['docker', 'compose', '--profile', 'ab', 'up', '-d', '--force-recreate', '--no-deps', 'app-prev'])


def up():
    run(['docker', 'compose', '--profile', 'ab', 'up', '-d', '--no-deps', 'app-v0', 'app-v1', 'app-v2', 'app-v3'])


def down():
    run(['docker', 'compose', '--profile', 'ab', 'stop', 'app-v0', 'app-v1', 'app-v2', 'app-v3', 'app-prev'])


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    {'baseline': baseline, 'prev': prev, 'up': up, 'down': down}.get(cmd, lambda: sys.exit(__doc__))()
