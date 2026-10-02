"""Targeted real-client history protection while independent publishing continues."""
import ctypes as C
from ctypes import wintypes as W
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

from chart_refresh import reload_active
from client_control import Client
from history_guard import HistoryGuard, fixed_cursor_visible, date_badge_hash
from settings import load

root = Path(sys.argv[1]).resolve(strict=True)
prefix = sys.argv[2] if len(sys.argv) > 2 else 'HISTORY-LIVE'
if not prefix.replace('-', '').isalnum():
    raise ValueError('Invalid evidence prefix')
receipt_path = root / (prefix + '-RECEIPT.json')
if receipt_path.exists():
    raise FileExistsError(receipt_path)
config = load(root / 'settings.json')
client = Client(config)
guard = HistoryGuard()


def selected_fields():
    pid = next(w[2] for w in client.windows() if 'V7.73' in w[1])
    handles = []
    @C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
    def callback(handle, unused):
        actual = W.DWORD()
        client.user.GetWindowThreadProcessId(handle, C.byref(actual))
        if actual.value == pid and client.user.IsWindowVisible(handle):
            handles.append(int(handle))
        return True
    client.user.EnumWindows(callback, 0)
    return {str(i['id']): i['name'] for h in handles for i in client.children(h)
            if i['class'] == 'Static' and 1354 <= i['id'] <= 1361}


def sample():
    database = Path(config['data_directory']) / 'market.sqlite3'
    db = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)
    try:
        event = db.execute('SELECT MAX(event_ms) FROM live_order').fetchone()[0]
    finally:
        db.close()
    cache = Path(config['tdx']['data_directory']) / 'ds/fzline/10#397906.lc5'
    bitmap = client.capture(None)['bitmap']
    return {'UTC': datetime.now(timezone.utc).isoformat(), 'fields': selected_fields(),
            'cursor_visible': fixed_cursor_visible(bitmap), 'date_badge': date_badge_hash(bitmap),
            'last_database_event_ms': event, 'lc5_sha256': hashlib.sha256(cache.read_bytes()).hexdigest(),
            'lc5_mtime_ns': cache.stat().st_mtime_ns}


before = after = first = second = None
try:
    before = sample()
    assert before['cursor_visible'], 'Select historical cursor first'
    first = reload_active(client, config['pairs'], guard)
    assert not first['requested']
    time.sleep(12)
    second = reload_active(client, config['pairs'], guard)
    after = sample()
    assert not second['requested']
    assert before['date_badge'] == after['date_badge'], 'Historical date badge moved'
    if before['fields'] and after['fields']:
        assert all(before['fields'].get(key) == after['fields'].get(key)
                   for key in ('1354', '1356', '1357', '1358', '1359')), 'Historical time/OHLC moved'
    assert after['last_database_event_ms'] > before['last_database_event_ms']
    assert after['lc5_mtime_ns'] > before['lc5_mtime_ns']
    client.capture(root / (prefix + '-held-chart.bmp'))
    result = subprocess.run([sys.executable, str(Path(__file__).with_name('trial_chart_probe.py')),
                             str(root), 'latest'], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    guard.navigation('latest')
    time.sleep(2)
    resumed = reload_active(client, config['pairs'], guard)
    deadline = time.monotonic() + 20
    while not resumed['requested'] and resumed.get('reason') == 'User input active; defer reload' and time.monotonic() < deadline:
        time.sleep(.5)
        resumed = reload_active(client, config['pairs'], guard)
    assert resumed['requested'], resumed
    time.sleep(.4)
    restored = sample()
    assert not restored['cursor_visible']
    client.capture(root / (prefix + '-return-latest-chart.bmp'))
    receipt = {'status': 'passed_with_scope', 'before': before, 'after': after,
               'historical_OHLC_visible_both_samples': bool(before['fields'] and after['fields']),
               'reload_while_history': [first, second], 'reload_after_explicit_latest': resumed,
               'restored': restored, 'scope': 'real independent ADA chart; history held >idle guard, database/files continued; explicit End/Escape resumed reload',
               'original_live_client_modified': False, 'accuracy_acceptance': False}
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'status': receipt['status'], 'history_time': before['fields'].get('1354', 'selected date badge retained; quote popup not visible'),
                      'database_updated': True, 'file_updated': True, 'reload_resumed': True}, ensure_ascii=True))
except Exception as error:
    receipt_path.write_text(json.dumps({'status': 'failed', 'error': str(error),
        'before': before, 'after': after, 'reloads': [first, second]}, ensure_ascii=False, indent=2), encoding='utf-8')
    raise
finally:
    guard.close()
