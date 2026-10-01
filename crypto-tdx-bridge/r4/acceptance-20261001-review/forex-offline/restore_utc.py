"""Restore only the two explicitly backed-up diagnostic minute files to UTC."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from ctypes import wintypes as W

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root.parents[1]))
from client_control import Client

config = json.loads((root / 'settings.json').read_text(encoding='utf-8'))
client = Client(config)
was_running = bool(client.windows())
for handle, _, _ in client.windows():
    client.user.PostMessageW(W.HWND(handle), 0x10, 0, 0)
time.sleep(.5)
for handle, _, _ in client.windows():
    for item in client.children(handle):
        if item['class'] == 'Button' and item['name'] == '\u9000\u51fa':
            client.user.PostMessageW(W.HWND(handle), 0x111, item['id'], item['handle'])
for _ in range(30):
    if not client.windows():
        break
    time.sleep(.2)
if client.windows():
    raise RuntimeError('Client still open; no files changed')

folder = root / 'local-time-utc7'
receipt = json.loads((folder / 'RECEIPT.json').read_text(encoding='utf-8'))
prepared = []
for item in receipt['changes']:
    target = (root / 'client' / item['path']).resolve()
    if not target.is_relative_to((root / 'client/vipdoc/ds').resolve()):
        raise ValueError('Restore target escapes isolated external quote directory')
    raw = (folder / item['backup']).read_bytes()
    if hashlib.sha256(raw).hexdigest() != item['before_sha256']:
        raise ValueError('Backup hash mismatch')
    current = hashlib.sha256(target.read_bytes()).hexdigest()
    if current not in (item['before_sha256'], item['after_sha256']):
        raise ValueError('Unexpected quote changes; refusing overwrite')
    prepared.append((target, raw, item))
for target, raw, item in prepared:
    temporary = target.with_suffix('.restore-temp')
    temporary.write_bytes(raw)
    os.replace(temporary, target)
    if hashlib.sha256(target.read_bytes()).hexdigest() != item['before_sha256']:
        raise ValueError('Restore readback failed')
(folder / 'UTC-RESTORE.json').write_text(json.dumps({
    'state': 'RESTORED_TO_UTC', 'display_offset_minutes': 0,
    'files': [{'path': item['path'], 'sha256': item['before_sha256']}
              for _, _, item in prepared],
    'exact_data_unchanged': True, 'user_decision': 'Keep UTC, no local-time conversion'},
    ensure_ascii=False, indent=2), encoding='utf-8')
if was_running:
    subprocess.Popen([str(client.executable)], cwd=client.executable.parent)
print('Restored diagnostic LC1/LC5 to original UTC bytes')
