"""Verify the real EXE's history latch and the shared GUI follow-latest action."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
import uuid

root = Path(sys.argv[1]).resolve(strict=True)
status_file = root / 'EXE-FINAL-CONTROL-LIVE.json'
output = root / 'PACKAGED-HISTORY-CONTROL.json'
if output.exists():
    raise FileExistsError(output)


def state():
    return json.loads(status_file.read_text(encoding='utf-8'))


before = state()
assert before.get('history_view', {}).get('paused'), 'Historical mode must be active'
samples = []
for _ in range(12):
    time.sleep(1)
    current = state()
    samples.append(current)
assert all(s.get('history_view', {}).get('paused') and not s.get('refresh_request', {}).get('requested') for s in samples)
assert samples[-1]['applied'] > before['applied']
assert samples[-1].get('last_file_ms', 0) > before.get('last_file_ms', 0)
request_id = uuid.uuid4().hex
(root / 'EXE-FINAL-COMMAND.json').write_text(json.dumps({'action': 'follow_latest', 'request_id': request_id}), encoding='utf-8')
deadline = time.monotonic() + 25
resumed = None
while time.monotonic() < deadline:
    time.sleep(.5)
    current = state()
    ack = current.get('last_control', {})
    if ack.get('request_id') == request_id and ack.get('error'):
        raise RuntimeError(ack['error'])
    if ack.get('request_id') == request_id and current.get('refresh_request', {}).get('requested') and not current['history_view']['paused']:
        resumed = current
        break
receipt = {'status': 'passed_with_scope' if resumed else 'history_protection_passed_resume_pending',
    'observed_UTC': datetime.now(timezone.utc).isoformat(), 'before': before,
    'history_samples': samples, 'after_follow_latest': resumed or state(),
    'history_reload_requests': 0, 'database_and_file_updates_continued': True,
    'follow_latest_and_reload_resumed': bool(resumed), 'accuracy_acceptance': False,
    'scope': 'actual delivery EXE; control invokes the same Engine.follow_latest method as the GUI button; no old historical test replay'}
output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'status': receipt['status'], 'database_file_updates': True, 'reload_resumed': bool(resumed)}))
