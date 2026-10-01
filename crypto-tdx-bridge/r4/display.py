"""Managed quote files: explicit lossy display conversion and atomic coalesced batches."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_EVEN
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import struct
import time
import uuid

from settings import registration_check

MINUTE = struct.Struct('<HHfffffII')
DAY = struct.Struct('<IIIIIfII')


def stamp(row):
    moment = datetime.fromtimestamp(row[0] / 1000, timezone.utc)
    day = (moment.year - 2004) * 2048 + moment.month * 100 + moment.day
    if not 0 <= day <= 65535 or row[0] % 60000:
        raise ValueError('Minute date exceeds candidate representation')
    return day, moment.hour * 60 + moment.minute


def encode(row, daily=False):
    values = []
    differences = {}
    for name, index in (('open', 1), ('high', 2), ('low', 3), ('close', 4), ('amount_usdt', 7)):
        exact = Decimal(row[index])
        if not exact.is_finite() or exact < 0:
            raise ValueError('Non-finite/negative exact value')
        if daily and index != 7:
            integer = int((exact * 1000).to_integral_value(rounding=ROUND_HALF_EVEN))
            if not 0 <= integer <= 0xffffffff:
                raise ValueError('DAY price overflow; no alternative scaling')
            values.append(integer)
            represented = Decimal(integer) / 1000
        else:
            value = struct.unpack('<f', struct.pack('<f', float(exact)))[0]
            if not math.isfinite(value):
                raise ValueError('float32 overflow; no scaling')
            values.append(value)
            represented = Decimal.from_float(value)
        differences[name] = {'original': row[index], 'represented': str(represented),
                             'error': str(represented - exact)}
    quantity = Decimal(row[5])
    integer = int(quantity)
    if not 0 <= integer <= 0xffffffff:
        raise ValueError('Base quantity exceeds uint32; no unit conversion')
    differences['base_volume'] = {'original': row[5], 'represented': str(integer),
        'error': str(Decimal(integer) - quantity), 'unit': 'base asset; truncated DISPLAY TRIAL',
        'positive_became_zero': quantity > 0 and integer == 0}
    if daily:
        date = int(datetime.fromtimestamp(row[0] / 1000, timezone.utc).strftime('%Y%m%d'))
        binary = DAY.pack(date, *values, integer, 0)
    else:
        binary = MINUTE.pack(*stamp(row), *values, integer, 0)
    return binary, differences


def decode_time(raw, daily):
    if daily:
        date = struct.unpack_from('<I', raw)[0]
        return int(datetime.strptime(str(date), '%Y%m%d').replace(tzinfo=timezone.utc).timestamp() * 1000)
    day, minute = struct.unpack_from('<HH', raw)
    year, monthday = day // 2048 + 2004, day % 2048
    if not 0 <= minute < 1440:
        raise ValueError('Existing cache has invalid minute')
    return int(datetime(year, monthday // 100, monthday % 100, minute // 60,
                        minute % 60, tzinfo=timezone.utc).timestamp() * 1000)


class Publisher:
    def __init__(self, config, status):
        self.config = config
        self.status = status
        self.home = Path(config['data_directory']) / 'display'
        self.home.mkdir(parents=True, exist_ok=True)
        self.root = Path(config['tdx']['data_directory']).resolve()
        self.managed_path = self.home / 'managed.json'
        self.managed = json.loads(self.managed_path.read_text()) if self.managed_path.exists() else {}
        self.cache = {}
        self.pending = {}
        self.recover_batches()

    def recover_batches(self):
        for receipt in (self.home / 'batches').glob('*/receipt.json'):
            record = json.loads(receipt.read_text(encoding='utf-8'))
            if record['state'] != 'PREPARED':
                continue
            for item in reversed(record['files']):
                target = Path(item['path']).resolve()
                if not target.is_relative_to(self.root):
                    raise ValueError('Journal target outside quote directory')
                old = receipt.parent / item['rollback_file']
                if item['old_exists']:
                    data = old.read_bytes()
                    if hashlib.sha256(data).hexdigest() != item['old_sha256']:
                        raise ValueError('Journal rollback hash mismatch')
                    temporary = target.with_name(target.name + '.recovery.tmp')
                    temporary.write_bytes(data)
                    os.replace(temporary, target)
                else:
                    target.unlink(missing_ok=True)
            record['state'] = 'ROLLED_BACK_AFTER_INTERRUPTION'
            self._json_atomic(receipt, record)

    def targets(self, pair):
        market, code = pair['market'], pair['code']
        return {'1m': self.root / market / 'minline' / f'{market}{code}.lc1',
                '5m': self.root / market / 'fzline' / f'{market}{code}.lc5',
                '1d': self.root / market / 'lday' / f'{market}{code}.day'}

    def claim(self, pair):
        allowed, reason = registration_check(self.config, pair, self.managed)
        if not allowed:
            raise ValueError(reason)
        key = pair['market'] + ':' + pair['code']
        if key not in self.managed:
            files = []
            for interval, path in self.targets(pair).items():
                if not path.resolve().is_relative_to(self.root):
                    raise ValueError('Output escapes actual data directory')
                backup = self.home / 'backup' / key.replace(':', '-') / path.relative_to(self.root)
                entry = {'path': str(path), 'existed': path.exists(), 'backup': backup.relative_to(self.home).as_posix()}
                if path.exists():
                    raw = path.read_bytes()
                    if len(raw) % 32:
                        raise ValueError('Existing file record alignment invalid')
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    backup.write_bytes(raw)
                    entry['sha256'] = hashlib.sha256(raw).hexdigest()
                files.append(entry)
            self.managed[key] = {'symbol': pair['symbol'], 'data_directory': str(self.root), 'files': files}
            self._json_atomic(self.managed_path, self.managed)
        elif self.managed[key]['data_directory'] != str(self.root):
            raise ValueError('Data directory changed; use separate local data directory to preserve ownership')

    @staticmethod
    def _json_atomic(path, value):
        temp = path.with_name(path.name + '.tmp')
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temp, path)

    def queue(self, pair, interval, rows):
        if interval not in self.targets(pair):
            return
        self.claim(pair)
        path = self.targets(pair)[interval]
        if path not in self.cache:
            raw = path.read_bytes() if path.exists() else b''
            if len(raw) % 32:
                raise ValueError('Existing cache is truncated')
            self.cache[path] = {decode_time(raw[i:i + 32], interval == '1d'): raw[i:i + 32]
                                for i in range(0, len(raw), 32)}
        dirty = self.pending.setdefault(path, {})
        for row in rows:
            raw, error = encode(row, interval == '1d')
            if self.cache[path].get(row[0]) != raw or row[0] in dirty:
                dirty[row[0]] = (raw, error)

    def flush(self):
        actual = {path: rows for path, rows in self.pending.items() if rows}
        if not actual:
            return False
        identity = uuid.uuid4().hex
        transaction = self.home / 'batches' / identity
        transaction.mkdir(parents=True)
        staged = []
        changes = []
        try:
            for index, (path, updates) in enumerate(actual.items()):
                old = path.read_bytes() if path.exists() else None
                # Do not stomp changes made by another producer while running.
                expected = b''.join(self.cache[path][opened] for opened in sorted(self.cache[path]))
                if old is not None and old != expected:
                    raise RuntimeError(f'External file changed concurrently: {path}')
                combined = dict(self.cache[path])
                combined.update({opened: values[0] for opened, values in updates.items()})
                new = b''.join(combined[opened] for opened in sorted(combined))
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_name(path.name + '.' + identity + '.tmp')
                with temporary.open('wb') as stream:
                    stream.write(new)
                    stream.flush()
                    os.fsync(stream.fileno())
                rollback_file = f'rollback-{index}.bin'
                with (transaction / rollback_file).open('wb') as stream:
                    stream.write(old or b'')
                    stream.flush()
                    os.fsync(stream.fileno())
                changes.append({'path': str(path), 'updated_records': len(updates),
                    'rollback_file': rollback_file, 'old_exists': old is not None,
                    'old_sha256': hashlib.sha256(old or b'').hexdigest(),
                    'records': len(combined), 'sha256': hashlib.sha256(new).hexdigest(),
                    'errors': [{'open_ms': opened, 'fields': values[1]} for opened, values in updates.items()]})
                staged.append((path, temporary, old, combined, new))
            self._json_atomic(transaction / 'receipt.json', {'batch_id': identity, 'state': 'PREPARED', 'files': changes})
            done = []
            try:
                for path, temporary, old, combined, new in staged:
                    os.replace(temporary, path)
                    done.append((path, old))
                for path, _, _, _, new in staged:
                    if path.read_bytes() != new:
                        raise RuntimeError('Quote file readback mismatch')
            except Exception:
                for path, old in reversed(done):
                    if old is None:
                        path.unlink(missing_ok=True)
                    else:
                        rollback = path.with_name(path.name + '.rollback.tmp')
                        rollback.write_bytes(old)
                        os.replace(rollback, path)
                self._json_atomic(transaction / 'receipt.json', {'batch_id': identity,
                    'state': 'ROLLED_BACK', 'files': changes})
                raise
            for path, _, _, combined, _ in staged:
                self.cache[path] = combined
                self.pending[path].clear()
            self._json_atomic(transaction / 'receipt.json', {'batch_id': identity, 'state': 'COMMITTED',
                'display_trial_only': True, 'utc_label': 'open minute', 'files': changes})
            self.status(last_file_ms=int(time.time() * 1000), file_error=None,
                        batch_id=identity, files=[{k: item[k] for k in ('path', 'records', 'sha256')} for item in changes])
            return True
        except Exception as error:
            self.status(file_error=str(error), pending_files=len(actual))
            self._json_atomic(transaction / 'failure.json', {'error': str(error), 'retry_pending': True})
            return False
        finally:
            for _, temporary, _, _, _ in staged:
                temporary.unlink(missing_ok=True)

    def restore(self):
        # Recovery is intentionally separate from the live publishing loop.
        for entry in self.managed.values():
            for file in entry['files']:
                path = Path(file['path']).resolve()
                if not path.is_relative_to(self.root):
                    raise ValueError('Restore target outside configured quote directory')
                if file['existed']:
                    backup = self.home / file['backup']
                    if hashlib.sha256(backup.read_bytes()).hexdigest() != file['sha256']:
                        raise ValueError('Backup hash mismatch')
                    temporary = path.with_name(path.name + '.restore.tmp')
                    temporary.write_bytes(backup.read_bytes())
                    os.replace(temporary, path)
                else:
                    path.unlink(missing_ok=True)
