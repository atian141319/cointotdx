"""Lossless content-addressed local archive; deletion is a separate PowerShell step."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timezone

root = Path(__file__).resolve().parent.parent
stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
out = root / 'r4' / ('cold-archive-' + stamp)
out.mkdir()
targets = [
    'r4/completion-20261002T114501Z/trial-client',
    'r4/completion-20261002T114517Z/trial-client',
    'r4/acceptance-20261002-head/successful-client',
    'r4/acceptance-20261002-2355/baseline-client',
    'r4/acceptance-20261002-2355/trial-client',
    'r4/acceptance-20261001-review/forex-offline/client',
    'r4/acceptance-20261001-review/session-diagnostic/client',
    'experiments/r3-lc1-user-test/client',
    'experiments/r3-lc1-user-test/backup/client-before-trial',
    'experiments/r3-lc1-user-test/r3a/daily-import-backup',
    'r4/acceptance-20261002-head/build',
    'r4/acceptance-20261002-head/build-auto',
    'r4/acceptance-20261002-head/build-final',
    'r4/acceptance-20261002-head/build-live',
    'r4/acceptance-20261002-head/final-exe-hour-burst-observations',
    'r4/acceptance-20261002-head/final-exe-next-hour-observations',
    'r4/acceptance-20261002-head/final-exe-online-observations',
]
# All duplicate review directories are preserved byte-for-byte in this archive.
head = root / 'r4/acceptance-20261002-head'
small_cleanup = any(flag in sys.argv for flag in ('--small-cleanup', '--legacy-evidence', '--finish-intermediates', '--other-project-artifacts'))
if small_cleanup:
    targets = [
        'r4/offline-fresh-20261001T113531Z',
        'r4/offline-fresh-20261001T113531Z-r2',
        'r4/offline-fresh-20261001T114123Z',
        'r4/acceptance-20261001-review/session-diagnostic/sdk-env',
        'r4/completion-20261002T114517Z/release',
        'r4/completion-20261002T114517Z/release-v2',
        'r4/completion-20261002T114517Z/release-v3',
        'r4/completion-20261002T114517Z/release-final',
        'r4/delivery-correction-20261002T133027Z',
    ]
if '--legacy-evidence' in sys.argv:
    targets = ['r4/acceptance-20261002-2355']
    legacy_root = root / 'r4/acceptance-20261001-review'
    targets.extend(p.relative_to(root).as_posix() for p in legacy_root.iterdir()
                   if p.is_dir() and not p.is_symlink() and not p.is_junction()
                   and p.name not in ('forex-offline', 'session-diagnostic'))
if '--finish-intermediates' in sys.argv:
    targets = [
        'r4/live-data', 'r4/evidence', 'r4/release',
        'r4/completion-20261002T114517Z/exact-data',
        'r4/completion-20261002T114501Z',
        'r4/acceptance-20261002-head/user-release-20261002T065429Z',
        'r4/acceptance-20261002-head/user-release-20261002T104951Z',
        'r4/__pycache__', 'r4/acceptance-20261002-head/__pycache__',
    ]
if '--other-project-artifacts' in sys.argv:
    targets = [p.relative_to(root).as_posix() for p in (root / 'artifacts').iterdir()
               if p.is_dir() and not p.is_junction() and not p.is_symlink()
               and not any(p.rglob('*.zip'))]
    targets += [
        'experiments/r3-lc1-user-test/evidence',
        'experiments/r3-lc1-user-test/samples',
        'experiments/r3-lc1-user-test/transactions',
        'experiments/r3-lc1-user-test/r3a/daily-txt-20261001',
        'experiments/r3-lc1-user-test/r3a/evidence',
        'experiments/r3-lc1-user-test/r3a/samples',
        'experiments/r3-lc1-user-test/r3a/multi-minute/batches',
        'experiments/r3-lc1-user-test/r3a/multi-minute/data',
        'experiments/r3-lc1-user-test/r3a/multi-minute/evidence',
        '__pycache__', 'tests/__pycache__', 'tools/__pycache__',
        'experiments/r3-lc1-user-test/__pycache__',
        'experiments/r3-lc1-user-test/r3a/__pycache__',
        'experiments/r3-lc1-user-test/r3a/multi-minute/__pycache__',
    ]
for pattern in ([] if small_cleanup else ['fresh-*', 'review-2026*', 'user-unpack-*']):
    targets.extend(p.relative_to(root).as_posix() for p in head.glob(pattern) if p.is_dir())
# Only settled journals older than 15 minutes; latest 100 and all PREPARED retained.
for relative in ([] if small_cleanup else ['r4/acceptance-20261002-head/live-data/display/batches', 'r4/live-data/display/batches']):
    batches = root / relative
    candidates = sorted((p for p in batches.glob('*') if p.is_dir()),
                        key=lambda p: p.stat().st_mtime, reverse=True)
    for p in candidates[100:]:
        receipt = p / 'receipt.json'
        if p.stat().st_mtime < time.time() - 900 and receipt.exists():
            record = json.loads(receipt.read_text(encoding='utf-8'))
            if record['state'] == 'COMMITTED':
                targets.append(p.relative_to(root).as_posix())
targets = sorted(set(t for t in targets if (root / t).is_dir()))
tracked = subprocess.check_output(['git', 'ls-files'], cwd=root, text=True).splitlines()
processes = json.loads(subprocess.check_output(['powershell', '-NoProfile', '-Command',
    "Get-CimInstance Win32_Process | Where-Object { $_.Name -notin @('powershell.exe','python.exe','pwsh.exe') } | Select-Object ExecutablePath,CommandLine | ConvertTo-Json"], text=True, encoding='utf-8', errors='replace'))
for t in targets:
    path = (root / t).resolve(strict=True)
    if not path.is_relative_to(root) or any(f == t or f.startswith(t + '/') for f in tracked):
        raise RuntimeError('Unsafe/tracked target: ' + t)
    for proc in processes:
        if str(path).lower() in ((proc.get('ExecutablePath') or '') + (proc.get('CommandLine') or '')).lower():
            raise RuntimeError('Active target: ' + t)
entries = []
objects = set()
archive = out / 'preserved.zip'
source_bytes = 0
with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for index, t in enumerate(targets):
        directory = root / t
        for base, dirs, files in os.walk(directory, followlinks=False):
            for name in dirs + files:
                p = Path(base) / name
                if p.is_symlink() or p.is_junction():
                    raise RuntimeError('Reparse point: ' + str(p))
            for name in files:
                p = Path(base) / name
                data = p.read_bytes()
                sha = hashlib.sha256(data).hexdigest()
                entries.append({'path':p.relative_to(root).as_posix(), 'sha256':sha, 'bytes':len(data)})
                source_bytes += len(data)
                if sha not in objects:
                    z.writestr('objects/' + sha, data)
                    objects.add(sha)
        if index % 100 == 0:
            print(json.dumps({'targets_done':index + 1, 'targets_total':len(targets), 'source_MiB':round(source_bytes/2**20)}), flush=True)
    manifest = {'project_root':str(root), 'utc':stamp, 'targets':targets, 'files':entries,
                'source_bytes':source_bytes, 'restore':'Use restore-cold-artifacts.py; does not overwrite existing files'}
    z.writestr('MANIFEST.json', json.dumps(manifest, ensure_ascii=False, indent=2))
with zipfile.ZipFile(archive) as z:
    for sha in objects:
        if hashlib.sha256(z.read('objects/' + sha)).hexdigest() != sha:
            raise RuntimeError('Archive object hash mismatch')
# Recheck sources before issuing a removal plan. Any change aborts all deletion.
for entry in entries:
    p = root / entry['path']
    if hashlib.sha256(p.read_bytes()).hexdigest() != entry['sha256']:
        raise RuntimeError('Source changed: ' + str(p))
archive_sha = hashlib.sha256(archive.read_bytes()).hexdigest()
(out / 'preserved.sha256').write_text(archive_sha + '  preserved.zip\n', encoding='ascii')
plan = {'archive':str(archive), 'archive_sha256':archive_sha, 'verified':True,
        'source_bytes':source_bytes, 'archive_bytes':archive.stat().st_size,
        'targets':[str(root / t) for t in targets], 'files':len(entries)}
(out / 'removal-plan.json').write_text(json.dumps(plan, indent=2), encoding='utf-8')
print(json.dumps({'plan':str(out/'removal-plan.json'), 'source_GiB':source_bytes/2**30,
                  'archive_GiB':archive.stat().st_size/2**30}), flush=True)
