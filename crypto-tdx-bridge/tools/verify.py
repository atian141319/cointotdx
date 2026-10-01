"""Offline independent verifier. No bridge import, network, schema creation or writes to inputs."""
import argparse
import csv
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from urllib.parse import parse_qs, urlparse


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative_name(name):
    """Accept legacy Windows separators without accepting Windows absolute paths."""
    if not isinstance(name, str) or not name or '\x00' in name:
        raise ValueError('Invalid package-relative path: ' + repr(name))
    windows = PureWindowsPath(name)
    normalized = name.replace('\\', '/')
    if windows.drive or windows.root or normalized.startswith('/') or ':' in normalized:
        raise ValueError('Invalid package-relative path: ' + name)
    if any(part in ('', '.', '..') for part in normalized.split('/')):
        raise ValueError('Invalid package-relative path: ' + name)
    return normalized


def safe_child(root, name):
    root = root.resolve()
    path = (root / relative_name(name)).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Path escapes package: ' + name)
    return path


def required(path):
    if not path.is_file():
        raise FileNotFoundError('Required file missing: ' + str(path))
    return path


def verify(db_path, raw_dir, export_dir, manifest_path):
    root = manifest_path.parent.resolve()
    package = json.loads(required(manifest_path).read_text(encoding='utf-8-sig'))
    listed = {}
    names = set()
    for entry in package['files']:
        name = relative_name(entry['path'])
        if name.casefold() in names:
            raise ValueError('Duplicate/case-colliding package entry: ' + name)
        names.add(name.casefold())
        path = required(safe_child(root, name))
        if path.stat().st_size != entry['size'] or digest(path) != entry['sha256']:
            raise ValueError('Package hash/size mismatch: ' + name)
        listed[name] = entry
    for path in (db_path, raw_dir, export_dir):
        if not path.resolve().is_relative_to(root):
            raise ValueError('Evidence input outside verified package: ' + str(path))
    def listed_file(path):
        required(path)
        name = path.resolve().relative_to(root).as_posix()
        if name not in listed:
            raise ValueError('Evidence file absent from package manifest: ' + name)
        return path
    listed_file(db_path)
    if not raw_dir.is_dir() or not export_dir.is_dir():
        raise FileNotFoundError('Raw/export directory missing')
    if Path(str(db_path)+'-wal').exists():
        raise ValueError('Use a sealed snapshot, not a database with a live WAL sidecar')
    con = sqlite3.connect(db_path.resolve().as_uri() + '?mode=ro&immutable=1', uri=True)
    try:
        con.execute('PRAGMA query_only=ON')
        if con.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('SQLite integrity failure')
        report = {'terminal_verified': False, 'network_used': False,
                  'database_readonly': True, 'manifest_files': len(listed),
                  'database_sha256': digest(db_path), 'checks': []}
        originals = {}
        for info_path in raw_dir.glob('*.json'):
            info = json.loads(listed_file(info_path).read_text(encoding='utf-8'))
            raw_id = info_path.stem
            body = listed_file(raw_dir / (raw_id + '.body')).read_bytes()
            if hashlib.sha256(body).hexdigest() != info['body_sha256']:
                raise ValueError('Raw body hash mismatch: ' + raw_id)
            url = urlparse(info['url'])
            if url.scheme != 'https' or url.hostname not in ('data-api.binance.vision', 'api.binance.com'):
                raise ValueError('Nonofficial raw source: ' + raw_id)
            parsed = json.loads(body) if info['status'] == 200 else None
            originals[raw_id] = (info, parsed, url, parse_qs(url.query))
        if {p.stem for p in raw_dir.glob('*.body')} != set(originals):
            raise ValueError('Orphan raw response or metadata')
        def raw_row(raw_id, symbol, interval, open_ms, payload):
            if raw_id not in originals:
                raise ValueError('Missing raw reference: ' + raw_id)
            info, parsed, url, query = originals[raw_id]
            if info['status'] != 200 or url.path != '/api/v3/klines' or query.get('symbol') != [symbol] or query.get('interval') != [interval]:
                raise ValueError('Raw request identity mismatch: ' + raw_id)
            if not isinstance(parsed, list) or not any(r[0] == open_ms and r == json.loads(payload) for r in parsed):
                raise ValueError('Database/raw row mismatch: ' + raw_id)
        row_count = 0
        for exchange, market, symbol, interval, open_ms, close_ms, payload, final, raw_id in con.execute('SELECT * FROM bars'):
            if exchange != 'binance' or market != 'spot' or final not in (0, 1):
                raise ValueError('Unsupported database identity/status')
            raw_row(raw_id, symbol, interval, open_ms, payload)
            row = json.loads(payload)
            if row[0] != open_ms or row[6] != close_ms:
                raise ValueError('Timestamp mismatch')
            row_count += 1
        revisions = 0
        for symbol, interval, open_ms, old, new, old_raw, new_raw in con.execute('SELECT symbol,interval,open_ms,old_payload,new_payload,old_raw,new_raw FROM revisions'):
            raw_row(old_raw, symbol, interval, open_ms, old)
            raw_row(new_raw, symbol, interval, open_ms, new)
            revisions += 1
        metadata_count = 0
        for symbol, payload, raw_id in con.execute('SELECT symbol,payload,raw_id FROM metadata'):
            info, parsed, url, query = originals[raw_id]
            if info['status'] != 200 or url.path != '/api/v3/exchangeInfo' or json.loads(payload) not in parsed['symbols'] or json.loads(payload)['symbol'] != symbol:
                raise ValueError('Metadata/raw mismatch: ' + symbol)
            metadata_count += 1
        empty_count = 0
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'empty_events' in tables:
            for symbol, interval, start, end, raw_id in con.execute('SELECT symbol,interval,start_ms,end_ms,raw_id FROM empty_events'):
                info, parsed, url, query = originals[raw_id]
                if info['status'] != 200 or parsed != [] or query.get('symbol') != [symbol] or query.get('interval') != [interval] or query.get('startTime') != [str(start)] or query.get('endTime') != [str(end-1)]:
                    raise ValueError('Empty interval/raw mismatch')
                empty_count += 1
        pointer_path = listed_file(export_dir / 'CURRENT.json')
        pointer = json.loads(pointer_path.read_text(encoding='utf-8'))
        batch = safe_child(export_dir.resolve(), pointer['batch'])
        export_manifest = listed_file(batch / 'manifest.json')
        if digest(export_manifest) != pointer['manifest_sha256']:
            raise ValueError('Export manifest hash mismatch')
        exported = json.loads(export_manifest.read_text(encoding='utf-8'))
        if batch.name != 'batch-' + exported['batch'] or exported['tdx_verified'] is not False:
            raise ValueError('Invalid batch identity/terminal claim')
        expected_scope = {(s, i) for s in exported['export_scope']['symbols'] for i in exported['export_scope']['intervals']}
        actual_scope = set()
        total_csv = 0
        for entry in exported['files']:
            identity = (entry['symbol'], entry['interval'])
            if identity in actual_scope:
                raise ValueError('Duplicate export series')
            actual_scope.add(identity)
            file = listed_file(safe_child(batch, entry['name']))
            if digest(file) != entry['sha256']:
                raise ValueError('CSV hash mismatch')
            expected = con.execute('SELECT payload,raw_id FROM bars WHERE symbol=? AND interval=? AND final=1 ORDER BY open_ms', identity).fetchall()
            with file.open(encoding='utf-8', newline='') as stream:
                rows = list(csv.DictReader(stream))
            if len(rows) != len(expected) or len(rows) != entry['rows']:
                raise ValueError('CSV missing/extra finalized rows')
            for row, (payload, raw_id) in zip(rows, expected):
                native = json.loads(payload)
                if (row['symbol'], row['interval']) != identity or row['raw_id'] != raw_id or row['source'] != 'binance-native':
                    raise ValueError('CSV identity/source mismatch')
                for key, index in [('open',1),('high',2),('low',3),('close',4),('base_volume',5),('quote_volume',7)]:
                    if row[key] != native[index]:
                        raise ValueError('CSV decimal precision loss: ' + key)
                for key, index in [('open_utc',0),('close_utc',6)]:
                    stamp = datetime.fromisoformat(row[key])
                    if stamp.utcoffset().total_seconds() != 0 or round(stamp.timestamp()*1000) != native[index]:
                        raise ValueError('CSV UTC/time mismatch')
                if row['trades'] != str(native[8]):
                    raise ValueError('CSV trades mismatch')
            total_csv += len(rows)
        if actual_scope != expected_scope:
            raise ValueError('Export series scope mismatch')
        report.update(result='VERIFIED_OFFLINE_EVIDENCE', stored_rows=row_count,
                      csv_rows=total_csv, raw_responses=len(originals), revisions=revisions,
                      metadata_rows=metadata_count, empty_events=empty_count,
                      export_files=len(actual_scope))
        report['checks'] = ['package SHA-256 and size', 'SQLite integrity and readonly',
                            'raw HTTP source/hash', 'bars/revisions/metadata/empty observations to raw',
                            'complete finalized CSV row coverage and exact decimal/time/source values']
        return report
    finally:
        con.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db', type=Path, required=True)
    p.add_argument('--raw-dir', type=Path, required=True)
    p.add_argument('--export-dir', type=Path, required=True)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--report-dir', type=Path, required=True)
    args = p.parse_args()
    root = args.manifest.resolve().parent
    report_dir = args.report_dir.resolve()
    if report_dir.is_relative_to(root):
        p.error('--report-dir must be outside the package directory')
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / 'offline-verification.json'
    if report_path.exists():
        p.error('report already exists; choose a new report directory')
    try:
        report = verify(args.db.resolve(), args.raw_dir.resolve(), args.export_dir.resolve(), args.manifest.resolve())
        code = 0
    except Exception as exc:
        report = {'result':'FAILED', 'network_used':False, 'error_type':type(exc).__name__, 'error':str(exc)}
        code = 1
    report['observed_utc'] = datetime.now(timezone.utc).isoformat()
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return code


if __name__ == '__main__':
    sys.exit(main())
