"""Read-only native LC5 comparison; no client or network operations."""
import collections
import datetime as dt
import hashlib
import json
from pathlib import Path
import struct

LAYOUT = struct.Struct('<HHfffffII')


def inspect(path):
    blob = path.read_bytes()
    if len(blob) % LAYOUT.size:
        raise ValueError('Non-32-byte-aligned file')
    rows = []
    for offset in range(0, len(blob), 32):
        values = LAYOUT.unpack_from(blob, offset)
        date, minute = values[:2]
        year, remainder = divmod(date, 2048)
        month, day = divmod(remainder, 100)
        timestamp = dt.datetime(year + 2004, month, day) + dt.timedelta(minutes=minute)
        rows.append({'offset': offset, 'time_label_no_timezone_claim': timestamp.isoformat(),
                     'minute': minute, 'ohlc': list(values[2:6]),
                     'field20_float32_candidate': values[6],
                     'field20_uint32_bits': struct.unpack_from('<I', blob, offset + 20)[0],
                     'volume_uint32_candidate': values[7], 'tail_uint32': values[8]})
    roundtrip = b''.join(LAYOUT.pack(*LAYOUT.unpack_from(blob, offset))
                         for offset in range(0, len(blob), 32))
    by_date = collections.defaultdict(list)
    for row in rows:
        by_date[row['time_label_no_timezone_claim'][:10]].append(row)
    transitions = []
    for index in range(1, len(rows)):
        if rows[index - 1]['time_label_no_timezone_claim'][:10] != rows[index]['time_label_no_timezone_claim'][:10]:
            transitions.append(rows[max(0, index - 3):index + 2])
    return {'source': str(path.resolve()), 'bytes': len(blob),
            'sha256': hashlib.sha256(blob).hexdigest(), 'records': len(rows),
            'roundtrip_byte_identical': roundtrip == blob,
            'minute_mod5_counts': dict(collections.Counter(r['minute'] % 5 for r in rows)),
            'records_at_2355': sum(r['minute'] == 1435 for r in rows),
            'records_at_2359': sum(r['minute'] == 1439 for r in rows),
            'tail_distinct_count': len(set(r['tail_uint32'] for r in rows)),
            'field20_uint32_range': [min(r['field20_uint32_bits'] for r in rows), max(r['field20_uint32_bits'] for r in rows)],
            'first': rows[:3], 'last': rows[-3:],
            'daily_ranges': [{'date': date, 'count': len(items),
                              'first': items[0]['time_label_no_timezone_claim'],
                              'last': items[-1]['time_label_no_timezone_claim']}
                             for date, items in by_date.items()],
            'date_transitions': transitions,
            'same_date_midnight_wraps': [rows[max(0, index - 2):index + 2]
                for index in range(1, len(rows))
                if rows[index]['time_label_no_timezone_claim'][:10] == rows[index - 1]['time_label_no_timezone_claim'][:10]
                and rows[index]['minute'] < rows[index - 1]['minute']],
            'all_2355_records': [r for r in rows if r['minute'] == 1435]}


if __name__ == '__main__':
    import sys
    source = Path(sys.argv[1]).resolve(strict=True)
    output = Path(sys.argv[2]).resolve()
    output.mkdir(parents=True, exist_ok=False)
    original = source.read_bytes()
    (output / source.name).write_bytes(original)
    native = inspect(output / source.name)
    native['original_source'] = str(source)
    result = {'native': native, 'interpretation': {
        'instrument': 'GC00Y, market prefix 16; gold-futures candidate, not proven FX',
        'timezone': 'UNCONFIRMED: native file has no timezone field',
        'field20': 'UNCONFIRMED: subnormal float32 values; do not treat as proven monetary amount',
        'time_label_semantics': 'UNCONFIRMED: file alone cannot prove open/close labels',
        'chart_merge': 'UNCONFIRMED: native higher-period chart not observed in this inspection'}}
    if len(sys.argv) > 3:
        coin_source = Path(sys.argv[3]).resolve(strict=True)
        coin_copy = output / coin_source.name
        coin_copy.write_bytes(coin_source.read_bytes())
        result['current_coin_snapshot'] = inspect(coin_copy)
        result['current_coin_snapshot']['original_source'] = str(coin_source)
    result['original_unchanged'] = source.read_bytes() == original
    (output / 'INSPECTION.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'directory': str(output), 'native_records': native['records'],
                      'native_2355': native['records_at_2355'], 'native_sha256': native['sha256'],
                      'roundtrip': native['roundtrip_byte_identical'], 'source_unchanged': result['original_unchanged']}))
