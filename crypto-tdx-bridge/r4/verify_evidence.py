"""Independent read-only, offline readback of an extracted R4 evidence directory."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import sqlite3
import struct


def relative(root, name):
    value = name.replace('\\', '/')
    if PureWindowsPath(name).drive or PurePosixPath(value).is_absolute() or '..' in PurePosixPath(value).parts:
        raise ValueError('Unsafe package path')
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError('Missing or escaped input: ' + name)
    return path


def verify(root):
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    for entry in manifest['files']:
        path = relative(root, entry['path'])
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
            raise ValueError('Hash mismatch: ' + entry['path'])
    database = relative(root, 'snapshot/market.sqlite3')
    totals = {'manifest_files': len(manifest['files']), 'raw_events': 0, 'bars': 0,
              'display_records': {}, 'source_aggregate_checks': {}, 'failures': []}
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Database integrity failed')
        for payload, path in db.execute('SELECT payload,raw_path FROM live_inbox'):
            raw = relative(root, 'snapshot/' + path)
            if json.loads(raw.read_text(encoding='utf-8')) != json.loads(payload):
                raise ValueError('Raw inbox mismatch')
            totals['raw_events'] += 1
        sources = {}
        for interval, opened, payload, raw in db.execute("SELECT interval,open_ms,payload,raw_id FROM bars WHERE symbol='BTCUSDT'"):
            row = json.loads(payload)
            source = relative(root, 'snapshot/raw/' + ('ws/' + raw + '.json' if raw.startswith('ws-') else raw + '.body'))
            data = json.loads(source.read_text(encoding='utf-8'))
            if raw.startswith('ws-'):
                k = data.get('data', data)['k']
                expected = [k[key] for key in ('t', 'o', 'h', 'l', 'c', 'v', 'T', 'q', 'n', 'V', 'Q', 'B')]
            else:
                expected = next((x for x in data if x[0] == opened), None)
            if expected != row:
                raise ValueError('Exact bar/raw mismatch')
            sources[interval, opened] = row
            totals['bars'] += 1
        for interval, filename, daily in [('1m','sz397901.lc1',False), ('5m','sz397901.lc5',False), ('1d','sz397901.day',True)]:
            raw = relative(root, 'snapshot/display/' + filename).read_bytes()
            if len(raw) % 32:
                raise ValueError('Misaligned display file')
            maximum = {key: Decimal(0) for key in ('open', 'high', 'low', 'close', 'amount', 'base_volume')}
            zero_volume = 0
            for position in range(0, len(raw), 32):
                record = struct.unpack_from('<IIIIIfII' if daily else '<HHfffffII', raw, position)
                if daily:
                    date = datetime.strptime(str(record[0]), '%Y%m%d').replace(tzinfo=timezone.utc)
                    fields = [Decimal(record[i]) / 1000 for i in range(1,5)] + [Decimal.from_float(record[5]), Decimal(record[6])]
                else:
                    year, md = record[0] // 2048 + 2004, record[0] % 2048
                    date = datetime(year, md // 100, md % 100, record[1] // 60, record[1] % 60, tzinfo=timezone.utc)
                    fields = [Decimal.from_float(x) for x in record[2:7]] + [Decimal(record[7])]
                opened = int(date.timestamp() * 1000)
                row = sources.get((interval, opened))
                if row is None:
                    raise ValueError('Display record has no precise source')
                for name, actual, index in zip(maximum, fields, (1,2,3,4,7,5)):
                    exact = Decimal(row[index]); error = abs(actual - exact)
                    maximum[name] = max(maximum[name], error)
                    if name == 'base_volume':
                        if actual != int(exact): raise ValueError('Unexpected quantity representation')
                        zero_volume += int(exact > 0 and actual == 0)
                    elif daily and name != 'amount':
                        if error > Decimal('.0005'): raise ValueError('DAY precision discrepancy')
                    else:
                        expected = Decimal.from_float(struct.unpack('<f', struct.pack('<f', float(exact)))[0])
                        if actual != expected: raise ValueError(f'Float32 discrepancy {interval} {opened} {name}: {actual} vs {expected}')
                if record[-1] != 0: raise ValueError('Display trial tail differs from declared hypothesis')
            totals['display_records'][interval] = {'records':len(raw)//32, 'max_absolute_error':{k:str(v) for k,v in maximum.items()}, 'positive_volume_became_zero':zero_volume}
        minute = {opened:row for (interval,opened),row in sources.items() if interval=='1m'}
        for interval, size in [('5m',5),('15m',15),('30m',30),('1h',60)]:
            checked = 0
            for (period, opened), native in sources.items():
                if period != interval: continue
                rows = [minute.get(opened+i*60000) for i in range(size)]
                if any(row is None for row in rows) or rows[-1][6] >= manifest['observed_ms']: continue
                values = [Decimal(rows[0][1]),max(Decimal(r[2]) for r in rows),min(Decimal(r[3]) for r in rows),Decimal(rows[-1][4]),sum(Decimal(r[5]) for r in rows),sum(Decimal(r[7]) for r in rows)]
                expected = [Decimal(native[i]) for i in (1,2,3,4,5,7)]
                if values != expected: totals['failures'].append({'interval':interval,'open_ms':opened,'reason':'native/1m aggregate mismatch'})
                checked += 1
            totals['source_aggregate_checks'][interval] = checked
    return totals


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if args.report.resolve().is_relative_to(args.package.resolve()):
        raise ValueError('Report must be outside hashed evidence package')
    result = verify(args.package.resolve())
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(result,indent=2),encoding='utf-8')
    if result['failures']: raise SystemExit(1)


if __name__ == '__main__': main()
