"""397901 BTC-only candidate LC1 publisher; no network or production export."""
import argparse
import hashlib
import json
from pathlib import Path
import uuid

import diagnostic

HERE = Path(__file__).resolve().parent
CLIENT = HERE.parent / 'client'
RELATIVE = 'vipdoc/sz/minline/sz397901.lc1'
BASELINE = HERE / 'external-minute-before.json'


def execute(action):
    diagnostic.closed()
    registry = CLIENT / 'T0002/lc/lcext.lei'
    if not registry.exists() or b'397901\x00BTCUSDT\x00' not in registry.read_bytes():
        raise RuntimeError('Verified external BTC identity 397901 is absent')
    destination = CLIENT / RELATIVE
    if not BASELINE.exists():
        old = destination.read_bytes() if destination.exists() else None
        backup = HERE / 'external-minute-original.lc1'
        if old is not None:
            backup.write_bytes(old)
        BASELINE.write_text(json.dumps({'path': RELATIVE, 'existed': old is not None,
            'sha256': hashlib.sha256(old).hexdigest() if old is not None else None,
            'backup': backup.name if old is not None else None}, indent=2))
    source = HERE / 'samples/C/sh999006.lc1'
    data = source.read_bytes()
    if action == 'restore':
        before = json.loads(BASELINE.read_text())
        if before['existed']:
            data = (HERE / before['backup']).read_bytes()
            if hashlib.sha256(data).hexdigest() != before['sha256']:
                raise RuntimeError('Backup hash mismatch')
            changes = diagnostic.r3().replace_group({RELATIVE: data}, 'Restore external minute baseline')
        else:
            saved = HERE / 'evidence' / ('removed-external-minute-' + uuid.uuid4().hex + '.lc1')
            if destination.exists():
                saved.write_bytes(destination.read_bytes())
                destination.unlink()
            changes = [{'path': RELATIVE, 'restored_absence': True}]
    else:
        if action == 'initial':
            data = data[:8 * 32]
        diagnostic.minute_report(data)
        changes = diagnostic.r3().replace_group({RELATIVE: data},
            '397901 BTC minute display trial ' + action)
        if destination.read_bytes() != data:
            raise RuntimeError('Published bytes differ')
    receipt = {'code': '397901', 'symbol': 'BTCUSDT', 'cache_namespace': 'sz',
        'action': action, 'changes': changes, 'minute_display': 'UNCONFIRMED',
        'lossy_display_trial': True, 'exact_source_modified': False,
        'errors_reference': '../samples/representation-errors.json',
        'readback': diagnostic.minute_report(data) if action != 'restore' else None}
    out = HERE / 'evidence' / ('external-minute-' + action + '-' + uuid.uuid4().hex + '.json')
    out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    print(out)
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['initial', 'update', 'restore'])
    execute(parser.parse_args().action)
