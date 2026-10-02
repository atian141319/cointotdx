"""Only the new-coin/native-control windows; immutable read-only inputs."""
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import re
import sqlite3
import struct
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import bridge
from display import decode_time, encode


def numeric(value):
    return float(re.match(r'\s*([-+]?\d+(?:\.\d+)?)', value).group(1))


def label(value):
    return datetime.strptime(value[:8] + ' ' + value[-5:], '%y/%m/%d %H:%M').replace(tzinfo=timezone.utc)


def aggregate(rows):
    return [Decimal(rows[0][1]), max(Decimal(r[2]) for r in rows),
            min(Decimal(r[3]) for r in rows), Decimal(rows[-1][4]),
            sum((Decimal(r[5]) for r in rows), Decimal()),
            sum((Decimal(r[7]) for r in rows), Decimal())]


root = Path(sys.argv[1]).resolve(strict=True)
if len(sys.argv) < 3:
    raise ValueError('Explicit report path outside the evidence/package is required')
output = Path(sys.argv[2]).resolve()
package_root = Path(sys.argv[3]).resolve(strict=True) if len(sys.argv) > 3 else root
if not root.is_relative_to(package_root) or output.is_relative_to(package_root):
    raise ValueError('Input must be inside package and report must be outside package')
if output.exists():
    raise FileExistsError(output)
from delivery_integrity import file_inventory, verify_manifest
before_inventory = file_inventory(package_root)
if (package_root / 'MANIFEST.json').is_file():
    verify_manifest(package_root, before_inventory)
database = root / 'exact-data/market.sqlite3'
if not database.is_file():
    raise FileNotFoundError(database)
db = sqlite3.connect(database.as_uri() + '?mode=ro&immutable=1', uri=True)
coin_checks = []
try:
    db.execute('BEGIN')
    bars = {interval: {opened: (json.loads(payload), bool(final)) for opened, payload, final in db.execute(
        'SELECT open_ms,payload,final FROM bars WHERE symbol=? AND interval=?', ('ADAUSDT', interval))}
        for interval in bridge.INTERVALS}
    cache = {}
    for interval, folder, extension in [('1m', 'minline', 'lc1'), ('5m', 'fzline', 'lc5')]:
        raw = (root / f'trial-client/vipdoc/ds/{folder}/10#397906.{extension}').read_bytes()
        cache[interval] = {decode_time(raw[i:i + 32], False, interval=interval,
            minute_label='last_minute' if interval == '5m' else 'open'): raw[i:i + 32]
            for i in range(0, len(raw), 32)}
    for interval, file in [('1m', 'ada-1m.json'), ('5m', 'ada-5m.json'), ('15m', 'ada-15m.json'),
                           ('30m', 'ada-30m-retry.json'), ('1h', 'ada-60m.json')]:
        observed = json.loads((root / file).read_text(encoding='utf-8'))
        seen = set()
        for fields in observed['rows']:
            if not fields.get('1354') or fields['1354'] in seen:
                continue
            seen.add(fields['1354'])
            stamp = int(label(fields['1354']).timestamp() * 1000)
            opened = bridge.floor(stamp, interval)
            ended = bridge.next_time(opened, interval)
            observed_ms = fields.get('_observed_ms')
            if observed_ms is None:
                observed_ms = json.loads((root / (Path(file).stem + '-chart.json')).read_text(encoding='utf-8'))['observed_ms']
            if opened < bridge.ms('2026-10-02T00:00:00Z'):
                continue
            if ended > observed_ms or (interval != '1m' and stamp != ended - 60000):
                coin_checks.append({'interval': interval, 'client_label': fields['1354'],
                                    'scope': 'current partial at observation; not closed acceptance',
                                    'observed_ms': observed_ms})
                continue
            source_interval = interval if interval in ('1m', '5m') else '5m'
            keys = list(range(opened, ended, 60000 if interval == '1m' else 300000))
            source = [bars[source_interval].get(key) for key in keys]
            if not all(item and item[1] for item in source):
                coin_checks.append({'interval': interval, 'client_label': fields['1354'],
                                    'scope': 'not final in snapshot; no closed acceptance'})
                continue
            exact = aggregate([item[0] for item in source])
            records = [cache[source_interval][key] for key in keys]
            encoded = [encode(item[0], interval=source_interval,
                minute_label='last_minute' if source_interval == '5m' else 'open')[0] for item in source]
            floats = [struct.unpack('<HHfffffII', record) for record in records]
            shown = [floats[0][2], max(r[3] for r in floats), min(r[4] for r in floats), floats[-1][5]]
            actual = [numeric(fields[str(i)]) for i in (1356, 1357, 1358, 1359)]
            native = bars[interval].get(opened)
            native_equal = bool(native and native[1] and aggregate([native[0]]) == exact)
            check = {'interval': interval, 'UTC_open': bridge.dt(opened).isoformat(),
                     'UTC_end_exclusive': bridge.dt(ended).isoformat(), 'client_label': fields['1354'],
                     'source_records': len(keys), 'source_complete_final': True,
                     'exact_aggregate_OHLC_base_quote': [str(v) for v in exact],
                     'source_native_period_exact_equal': native_equal,
                     'actual_cache_bytes_equal_display_conversion': records == encoded,
                     'converted_OHLC': shown, 'client_OHLC': actual,
                     'client_matches_at_five_decimals': all(f'{a:.5f}' == f'{b:.5f}' for a, b in zip(actual, shown)),
                     'integer_display_base_volume': sum(r[7] for r in floats),
                     'base_volume_loss': str(Decimal(sum(r[7] for r in floats)) - exact[4]),
                     'price_errors': [str(Decimal.from_float(value) - reference) for value, reference in zip(shown, exact[:4])],
                     'accuracy_acceptance': False}
            coin_checks.append(check)
finally:
    db.close()

native_blob = (root / 'trial-client/vipdoc/ds/fzline/16#GC00Y.lc5').read_bytes()
native_records = list(struct.iter_unpack('<HHfffffII', native_blob))
native_groups = {}
for size in (15, 30, 60):
    count = size // 5
    for index, record in enumerate(native_records):
        if record[1] % size:
            continue
        group = native_records[max(0, index - count + 1):index + 1]
        if len(group) != count or any(r[0] != record[0] for r in group):
            continue
        if any((group[i][1] - group[i - 1][1]) % 1440 != 5 for i in range(1, count)):
            continue
        native_groups[(size, record[0], record[1])] = group
native_checks = []
for size, file in [(15, 'native16-15m.json'), (30, 'native16-30m.json'), (60, 'native16-60m.json')]:
    seen = set()
    for fields in json.loads((root / file).read_text(encoding='utf-8'))['rows']:
        if not fields.get('1354') or fields['1354'] in seen:
            continue
        seen.add(fields['1354'])
        timestamp = label(fields['1354'])
        encoded_date = (timestamp.year - 2004) * 2048 + timestamp.month * 100 + timestamp.day
        minute = timestamp.hour * 60 + timestamp.minute
        group = native_groups.get((size, encoded_date, minute))
        if not group:
            native_checks.append({'period_minutes': size, 'client_label': fields['1354'], 'complete_input_window': False})
            continue
        expected = [group[0][2], max(r[3] for r in group), min(r[4] for r in group), group[-1][5]]
        actual = [numeric(fields[str(i)]) for i in (1356, 1357, 1358, 1359)]
        native_checks.append({'period_minutes': size, 'client_label': fields['1354'],
            'input_minutes_same_encoded_date': [r[1] for r in group], 'input_records': len(group),
            'complete_input_window': True, 'native_float32_OHLC': expected, 'client_OHLC': actual,
            'OHLC_matches_at_native_one_decimal': all(f'{a:.1f}' == f'{b:.1f}' for a, b in zip(actual, expected)),
            'client_quantity_text': fields.get('1360'), 'client_other_field_text': fields.get('1361'),
            'amount_and_trade_date_semantics': 'UNCONFIRMED; no currency interpretation'})
closed = [c for c in coin_checks if c.get('source_complete_final')]
native_complete = [c for c in native_checks if c.get('complete_input_window')]
receipt = {'status': 'passed_with_scope' if closed and all(c['client_matches_at_five_decimals'] and
    c['actual_cache_bytes_equal_display_conversion'] and c['source_native_period_exact_equal'] for c in closed)
    and native_complete and all(c['OHLC_matches_at_native_one_decimal'] for c in native_complete) else 'needs_review',
    'coin_checks': coin_checks, 'native_market16_checks': native_checks,
    'coin_closed_windows_checked': len(closed), 'native_complete_windows_checked': len(native_complete),
    'scope': 'new ADA closed 1/5/15/30/60 minute OHLC windows + actual native COMEX control windows, not old historical rerun',
    'UTC_source_unchanged': True, 'accuracy_acceptance': False,
    'midnight_weekend_dynamic': 'scheduled, not passed'}
after_inventory = file_inventory(package_root)
if before_inventory != after_inventory:
    raise RuntimeError('Delivery file list or hashes changed during verification')
receipt['frozen_database_uri'] = 'mode=ro&immutable=1'
receipt['input_files_before'] = before_inventory
receipt['input_files_after'] = after_inventory
receipt['input_file_set_and_hashes_unchanged'] = True
output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({key: value for key, value in receipt.items() if key not in (
    'coin_checks', 'native_market16_checks', 'input_files_before', 'input_files_after')}))
