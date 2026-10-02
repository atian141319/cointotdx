"""Validated reversible session edit for the isolated, observed market-10 trial.

Locate the record by identity, never by an offset from a different installation.
The profile remains experimental; this does not define all TongdaXin Fz fields.
"""
import hashlib
import json
import os
from pathlib import Path
import struct
import uuid

NATIVE_10 = (300, 1725, 1725, 1725, 1725, 1725, 1725, 1725, 295, 1730)
CONTINUOUS_05 = (300, 1740, 1740, 1740, 1740, 1740, 1740, 1740, 300, 1745)
RECORD_BYTES = 34


def locate(data, market_id=10):
    if not data or len(data) % RECORD_BYTES:
        raise ValueError('Unknown session file alignment')
    signature = bytes([market_id]) + b'?' * 8 + b'\0'
    positions = [offset for offset in range(0, len(data), RECORD_BYTES)
                 if data[offset:offset + 10] == signature]
    if len(positions) != 1:
        raise ValueError('Session identity absent or ambiguous')
    position = positions[0]
    if data[position + 30:position + 34] != struct.pack('<I', 1):
        raise ValueError('Unexpected session record tail')
    return position, struct.unpack_from('<10H', data, position + 10)


def converted(data, expected, replacement=CONTINUOUS_05):
    position, actual = locate(data)
    if actual != tuple(expected):
        raise ValueError(f'Session original values changed: {actual}')
    if len(replacement) != 10 or any(type(v) is not int or not 0 <= v <= 65535 for v in replacement):
        raise ValueError('Invalid session replacement')
    updated = bytearray(data)
    struct.pack_into('<10H', updated, position + 10, *replacement)
    assert updated[:position + 10] == data[:position + 10]
    assert updated[position + 30:] == data[position + 30:]
    return bytes(updated), position


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _atomic(path, data):
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temp.open('wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def apply(path, backup_directory, expected, *, client_running):
    if client_running:
        raise RuntimeError('Close the isolated client before changing its session configuration')
    path = Path(path).resolve(strict=True)
    old = path.read_bytes()
    new, position = converted(old, expected)
    folder = Path(backup_directory) / uuid.uuid4().hex
    folder.mkdir(parents=True, exist_ok=False)
    (folder / 'original.dat').write_bytes(old)
    receipt = {'schema': 1, 'target': str(path), 'market_id': 10,
               'selector_hex': (bytes([10]) + b'?' * 8 + b'\0').hex(),
               'located_offset_this_file_only': position,
               'old_values': list(expected), 'new_values': list(CONTINUOUS_05),
               'old_sha256': _hash(old), 'new_sha256': _hash(new),
               'backup': 'original.dat', 'profile': 'continuous-05-display-trial'}
    (folder / 'receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    if path.read_bytes() != old:
        raise RuntimeError('Session file changed while backing up; no configuration write')
    _atomic(path, new)
    if path.read_bytes() != new:
        raise RuntimeError('Session write readback failed')
    return folder / 'receipt.json'


def restore(receipt_path, *, client_running):
    if client_running:
        raise RuntimeError('Close the isolated client before restoring session configuration')
    receipt_path = Path(receipt_path)
    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    path = Path(receipt['target']).resolve(strict=True)
    old = (receipt_path.parent / 'original.dat').read_bytes()
    if _hash(old) != receipt['old_sha256']:
        raise ValueError('Session backup hash mismatch')
    if _hash(path.read_bytes()) != receipt['new_sha256']:
        raise ValueError('Session changed since this trial; refusing to overwrite')
    _atomic(path, old)
    return _hash(path.read_bytes())
