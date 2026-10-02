"""Graceful source-runner handoff without changing the accepted live settings."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

root = Path(__file__).resolve().parent / 'acceptance-20261002-head'
evidence = Path(sys.argv[1]).resolve(strict=True)
stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
config = root / 'live-settings.json'
original_hash = hashlib.sha256(config.read_bytes()).hexdigest()
pid = int((root / 'live-pid.txt').read_text().strip())
description = subprocess.check_output(['powershell', '-NoProfile', '-Command',
    f'Get-CimInstance Win32_Process -Filter "ProcessId={pid}" | Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress'],
    text=True, encoding='utf-8', errors='replace')
process = json.loads(description)
runner = root / 'live_runner.py'
if process['ProcessId'] != pid or str(runner) not in process['CommandLine']:
    raise RuntimeError('Runner identity mismatch; no stop request')
(root / 'STOP-LIVE').touch()
import ctypes as C
from ctypes import wintypes as W
kernel = C.WinDLL('kernel32', use_last_error=True)
kernel.OpenProcess.restype = W.HANDLE
kernel.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
kernel.CloseHandle.argtypes = [W.HANDLE]
handle = kernel.OpenProcess(0x100000, False, pid)
if not handle:
    raise C.WinError(C.get_last_error())
try:
    if kernel.WaitForSingleObject(handle, 60000) != 0:
        raise RuntimeError('Old runner did not exit; no replacement launched')
finally:
    kernel.CloseHandle(handle)
assert hashlib.sha256(config.read_bytes()).hexdigest() == original_hash
with (evidence / ('live-after-fix-' + stamp + '.stdout.log')).open('x', encoding='utf-8') as out, \
     (evidence / ('live-after-fix-' + stamp + '.stderr.log')).open('x', encoding='utf-8') as err:
    replacement = subprocess.Popen([sys.executable, str(runner)], cwd=str(root.parents[1]),
        stdout=out, stderr=err, creationflags=subprocess.CREATE_NO_WINDOW)
(root / 'live-pid.txt').write_text(str(replacement.pid), encoding='ascii')
(evidence / ('LIVE-SAFE-HANDOFF-' + stamp + '.json')).write_text(json.dumps({
    'observed_UTC': datetime.now(timezone.utc).isoformat(), 'old_pid': pid,
    'old_process_exited_before_new_launch': True, 'new_pid': replacement.pid,
    'live_config_sha256': original_hash, 'live_config_unchanged': True,
    'client_restart': False, 'original_installation_modified': False}, indent=2), encoding='utf-8')
print(json.dumps({'old_exited': pid, 'new_pid': replacement.pid, 'configuration_unchanged': True}))
