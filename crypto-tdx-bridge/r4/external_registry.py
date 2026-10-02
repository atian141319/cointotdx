"""Owned, reversible external-FX display registrations in an isolated client."""
import hashlib
import json
import os
from pathlib import Path
import uuid


def identity(pair):
    return f"ds:{pair['market_id']}:{pair['code']}" if pair['market'] == 'ds' else pair['market'] + ':' + pair['code']


def check(root, pair):
    root = Path(root)
    manifest = root / 'T0002/hq_cache/crypto-tdx-owned.json'
    if not manifest.is_file():
        return False, 'External registration pending: owned catalogue manifest missing'
    owners = json.loads(manifest.read_text(encoding='utf-8'))['instruments']
    item = owners.get(identity(pair))
    if not item or item['symbol'] != pair['symbol']:
        return False, 'External registration pending or owned by another symbol'
    raw = (root / 'T0002/hq_cache/ds_stk.dat').read_bytes()
    record = bytes.fromhex(item['record_hex'])
    if raw.count(record) != 1:
        return False, 'Owned external catalogue record missing or duplicated'
    return True, 'Owned basic-FX display trial; UTC; copied native display attributes'


def register(config, pairs):
    from client_control import Client
    if Client(config).windows():
        raise ValueError('Close the selected isolated client before registration; no force termination')
    root = Path(config['tdx']['installation']).resolve()
    registry = root / 'T0002/hq_cache/ds_stk.dat'
    manifest = registry.with_name('crypto-tdx-owned.json')
    original = registry.read_bytes()
    owners = json.loads(manifest.read_text(encoding='utf-8')) if manifest.exists() else {'instruments': {}}
    start = original.index(b'EURUSD') - 5
    template = original[start:start + 106]
    if template[:5] != bytes.fromhex('040a050000') or template[28:38].decode('gbk') != '\u6b27\u5143\u5151\u7f8e\u5143':
        raise ValueError('Observed FX template does not match; refuse guessed registry edits')
    appended = bytearray()
    for pair in pairs:
        if pair['market'] != 'ds' or pair.get('market_id') != 10:
            raise ValueError('Only the observed basic-FX diagnostic route is supported here')
        key = identity(pair)
        if key in owners['instruments']:
            allowed, reason = check(root, pair)
            if not allowed:
                raise ValueError(reason)
            continue
        code = pair['code'].encode('ascii')
        if code in original or code in appended:
            raise ValueError('Catalogue code collision: ' + pair['code'])
        name_text = pair.get('display_name', pair['symbol'] + '\u8bd5\u9a8c')
        if '\u8bd5\u9a8c' not in name_text:
            name_text += '\u8bd5\u9a8c'
        name = name_text.encode('gbk')
        if len(name) > 20:
            raise ValueError('Display name too long for observed name region')
        record = bytearray(template)
        record[5:28] = code.ljust(23, b'\0')
        record[28:48] = name.ljust(20, b'\0')
        appended.extend(record)
        owners['instruments'][key] = {'symbol': pair['symbol'], 'name': name.decode('gbk'),
            'record_hex': record.hex(), 'display_trial_only': True,
            'native_units_not_accuracy_approved': True}
    if not appended:
        return owners
    if any(p.get('lc5_time_label') == 'last_minute' for p in pairs):
        from session_config import locate, apply, NATIVE_10, CONTINUOUS_05
        session = registry.with_name('ds_tinf.dat')
        _, values = locate(session.read_bytes())
        if values == NATIVE_10:
            session_receipt = apply(session, Path(config['data_directory']) / 'session-backup',
                                    NATIVE_10, client_running=False)
            owners['session_receipt'] = str(session_receipt)
        elif values != CONTINUOUS_05:
            raise ValueError('Unknown session profile; no guessed time fields written')
    backup = Path(config['data_directory']) / 'registration-backup' / uuid.uuid4().hex
    backup.mkdir(parents=True)
    (backup / 'ds_stk.dat').write_bytes(original)
    if manifest.exists():
        (backup / 'crypto-tdx-owned.json').write_bytes(manifest.read_bytes())
    owners['last_backup'] = str(backup)
    owners['original_sha256'] = hashlib.sha256(original).hexdigest()
    temporary = registry.with_suffix('.crypto-temp')
    temporary.write_bytes(original + appended)
    manifest_temp = manifest.with_suffix('.crypto-temp')
    manifest_temp.write_text(json.dumps(owners, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, registry)
    try:
        os.replace(manifest_temp, manifest)
    except Exception:
        temporary.write_bytes(original)
        os.replace(temporary, registry)
        raise
    if not registry.read_bytes().startswith(original):
        raise ValueError('Original catalogue prefix changed')
    return owners
