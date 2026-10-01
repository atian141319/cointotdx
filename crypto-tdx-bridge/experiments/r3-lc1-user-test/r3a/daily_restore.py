"""Remove only the two newly created daily-import files, after normal exit."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import uuid

root = Path(__file__).resolve().parent
client = root.parent / 'client'
count = subprocess.check_output(['powershell', '-NoProfile', '-Command',
    "@(Get-CimInstance Win32_Process -Filter \"Name='tdxw.exe'\" -ErrorAction Stop).Count"], text=True)
if int(count.strip()):
    raise RuntimeError('Close all TongdaXin windows normally first; no force termination')
allowed = {'vipdoc/sz/lday/sz397901.day', 'T0002/lc/lcext.lei'}
changes = json.loads((root / 'evidence/daily-import-file-changes.json').read_text())
targets = [item for item in changes if item['path'] in allowed]
if len(targets) != 2 or any(item['before'] is not None for item in targets):
    raise RuntimeError('Expected precisely two newly created import files')
receipt = root / 'evidence' / ('daily-restore-' + uuid.uuid4().hex)
for item in targets:
    path = client / item['path']
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
        raise RuntimeError(f'File changed after receipt: {path}; no deletion performed')
receipt.mkdir()
for item in targets:
    path = client / item['path']
    if path.exists():
        backup = receipt / item['path']
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup)
for item in targets:
    (client / item['path']).unlink(missing_ok=True)
(receipt / 'receipt.json').write_text(json.dumps({'removed': list(allowed),
    'client': str(client), 'state': 'Restored pre-import absence; R3A controls retained'}, indent=2))
print(receipt)
