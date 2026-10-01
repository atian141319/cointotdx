"""Separate BTC 397901 minute-cache experiment; signed collector remains untouched."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal, Inexact, localcontext
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import uuid

HERE = Path(__file__).resolve().parent
RA = HERE.parent
PROJECT = HERE.parents[3]
CLIENT = HERE.parents[1] / 'client'
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(RA))
import bridge
import diagnostic

START = bridge.ms('2026-09-26T12:00:00Z')
INITIAL_END = bridge.ms('2026-09-27T12:00:00Z')
UPDATE_END = bridge.ms('2026-09-28T12:00:00Z')
PATHS = ('vipdoc/sz/minline/sz397901.lc1', 'vipdoc/sz/fzline/sz397901.lc5')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def initialize():
    source = PROJECT / 'data'
    data = HERE / 'data'
    database = data / 'market.sqlite3'
    if database.exists():
        return
    data.mkdir(parents=True, exist_ok=True)
    before = sha(source / 'market.sqlite3')
    with closing(sqlite3.connect((source / 'market.sqlite3').as_uri() + '?mode=ro', uri=True)) as original:
        with closing(sqlite3.connect(database)) as target:
            original.backup(target)
    shutil.copytree(source / 'raw', data / 'raw', dirs_exist_ok=True)
    after = sha(source / 'market.sqlite3')
    if before != after:
        raise RuntimeError('Original database changed while copying')
    write_json(HERE / 'evidence/source-preservation.json', {
        'original_database': str(source / 'market.sqlite3'), 'sha256': before,
        'unchanged': True, 'copy': 'data/market.sqlite3',
        'one_minute_display': 'USER_CONFIRMED_LIMITED_PASS',
        'other_periods': 'PENDING', 'overall': 'PARTIAL'})


def load_config():
    return bridge.config(HERE / 'config.json')


def collect():
    initialize()
    c = load_config()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
        handlers=[logging.FileHandler(HERE / 'evidence/collection.log', encoding='utf-8'), logging.StreamHandler()])
    with bridge.Instance(c['data_dir']):
        store = bridge.Store(c['data_dir'])
        try:
            api = bridge.API(c)  # Same persistent IP-scoped RateGate as signed collector.
            bridge.validate_metadata(api, store, c)
            gaps = store.gaps('BTCUSDT', '1m', START, UPDATE_END)
            for start, end in gaps:
                bridge.download(api, store, c, 'BTCUSDT', '1m', start, end)
            remaining = store.gaps('BTCUSDT', '1m', START, UPDATE_END)
            write_json(HERE / 'evidence/collection-result.json', {
                'start_utc': bridge.dt(START).isoformat(), 'end_exclusive_utc': bridge.dt(UPDATE_END).isoformat(),
                'remaining_gaps': remaining, 'rate_state': api.gate.inspect(),
                'raw_count': len(list((HERE / 'data/raw').glob('*.body'))),
                'original_database_unchanged': sha(PROJECT / 'data/market.sqlite3') ==
                    json.loads((HERE / 'evidence/source-preservation.json').read_text())['sha256']})
            if remaining:
                raise RuntimeError('Real minute coverage incomplete; publication blocked')
        finally:
            store.db.close()


def read_rows(start, end):
    path = HERE / 'data/market.sqlite3'
    if not path.is_file():
        raise FileNotFoundError('Run collect first')
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        records = db.execute("SELECT payload,raw_id FROM bars WHERE exchange='binance' "
            "AND market='spot' AND symbol='BTCUSDT' AND interval='1m' AND final=1 "
            "AND open_ms>=? AND open_ms<? ORDER BY open_ms", (start, end)).fetchall()
    rows = [json.loads(record[0]) for record in records]
    if [row[0] for row in rows] != list(range(start, end, 60000)):
        raise ValueError('Incomplete or unclosed minute source; cannot publish')
    return rows, sorted({record[1] for record in records})


def aggregate(rows, minutes):
    """UTC continuous buckets; absent minutes produce explicit incomplete windows."""
    groups = {}
    for row in rows:
        boundary = row[0] // (minutes * 60000) * (minutes * 60000)
        groups.setdefault(boundary, []).append(row)
    complete = []
    incomplete = []
    with localcontext() as context:
        context.prec = 128
        context.traps[Inexact] = True
        for start, group in sorted(groups.items()):
            group.sort(key=lambda row: row[0])
            expected = list(range(start, start + minutes * 60000, 60000))
            if [row[0] for row in group] != expected:
                incomplete.append({'start_ms': start, 'minutes': minutes,
                    'present': [row[0] for row in group], 'expected': expected})
                continue
            total = lambda column: format(sum((Decimal(row[column]) for row in group), Decimal(0)), 'f')
            complete.append([start, group[0][1],
                format(max(Decimal(row[2]) for row in group), 'f'),
                format(min(Decimal(row[3]) for row in group), 'f'), group[-1][4],
                total(5), start + minutes * 60000 - 1, total(7),
                sum(row[8] for row in group), total(9), total(10), '0'])
    return complete, incomplete


def build(end):
    rows, references = read_rows(START, end)
    batch = HERE / 'batches' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex)
    batch.mkdir(parents=True)
    trial = diagnostic.r3()
    counts = {}
    errors = {}
    for minutes in (1, 5, 15, 30, 60):
        candles, incomplete = aggregate(rows, minutes)
        if incomplete:
            write_json(batch / f'incomplete-{minutes}.json', incomplete)
            raise ValueError(f'Incomplete {minutes} minute periods; publication blocked')
        binary = bytearray()
        differences = []
        for candle in candles:
            packed, error = trial.pack_row(candle)
            binary.extend(packed)
            differences.append(error)
        write_json(batch / f'exact-{minutes}m.json', candles)
        write_json(batch / f'errors-{minutes}m.json', differences)
        # Only 1 and 5-minute files are candidate terminal caches.
        # 15/30/60 binaries are deliberately not generated.
        if minutes in (1, 5):
            path = batch / f'sz397901.lc{minutes}'
            path.write_bytes(binary)
            write_json(batch / f'readback-{minutes}m.json', diagnostic.minute_report(bytes(binary)))
        counts[str(minutes)] = len(candles)
        errors[str(minutes)] = {
            'max_price_absolute_error': str(max(Decimal(e['float_fields'][name]['absolute_error'])
                for e in differences for name in ('open', 'high', 'low', 'close'))),
            'max_amount_absolute_error': str(max(Decimal(e['float_fields']['quote_amount']['absolute_error']) for e in differences)),
            'quantity_positive_became_zero': sum(e['volume']['positive_quantity_became_zero'] for e in differences)}
    manifest = {'batch_id': batch.name, 'start_utc': bridge.dt(START).isoformat(),
        'end_exclusive_utc': bridge.dt(end).isoformat(), 'counts_complete': counts,
        'raw_ids': references, 'symbol': 'BTCUSDT', 'code': '397901', 'market_cache': 'sz',
        'timestamp_label': 'UTC open minute; unchanged from successful LC1 trial',
        'precision': 'Explicit R3 display-only float32 and quantity truncation, tail zero hypothesis',
        'aggregate_source': 'Exact SQLite minute decimal strings, never truncated LC1',
        'errors': errors, 'files': [{'path': p.name, 'sha256': sha(p), 'bytes': p.stat().st_size}
            for p in sorted(batch.iterdir())]}
    write_json(batch / 'manifest.json', manifest)
    return batch, manifest


def backup_once():
    diagnostic.closed()
    baseline = HERE / 'backup/manifest.json'
    if baseline.exists():
        return
    items = []
    for relative in PATHS:
        source = CLIENT / relative
        entry = {'path': relative, 'exists': source.is_file()}
        if source.exists():
            target = HERE / 'backup/files' / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            entry['sha256'] = sha(source)
            if sha(target) != entry['sha256']:
                raise ValueError('Backup mismatch')
        items.append(entry)
    write_json(baseline, {'client': str(CLIENT), 'files': items})


def publish(end):
    diagnostic.closed()
    registry = CLIENT / 'T0002/lc/lcext.lei'
    if b'397901\x00BTCUSDT\x00' not in registry.read_bytes():
        raise RuntimeError('Existing external identity is not BTC397901; no registration edits')
    backup_once()
    batch, manifest = build(end)
    changes = {PATHS[0]: (batch / 'sz397901.lc1').read_bytes(),
               PATHS[1]: (batch / 'sz397901.lc5').read_bytes()}
    result = diagnostic.r3().replace_group(changes, 'Multi-minute batch ' + batch.name)
    for relative, content in changes.items():
        if (CLIENT / relative).read_bytes() != content:
            raise RuntimeError('Publication readback mismatch')
    receipt = {'batch': batch.relative_to(HERE).as_posix(), 'batch_id': batch.name,
        'manifest': manifest, 'changes': result, 'one_minute_display': 'USER_CONFIRMED_LIMITED_PASS',
        'other_period_display': 'PENDING', 'reload': 'Client was closed; start and inspect'}
    write_json(HERE / 'evidence' / ('publish-' + batch.name + '.json'), receipt)
    write_json(HERE / 'active.json', receipt)
    print(json.dumps({'batch': str(batch), 'counts': manifest['counts_complete']}, indent=2))


def restore():
    diagnostic.closed()
    manifest = json.loads((HERE / 'backup/manifest.json').read_text())
    changes = {}
    remove = []
    for item in manifest['files']:
        if item['path'] not in PATHS:
            raise ValueError('Restore path outside trial scope')
        if item['exists']:
            source = HERE / 'backup/files' / item['path']
            if sha(source) != item['sha256']:
                raise ValueError('Backup hash mismatch')
            changes[item['path']] = source.read_bytes()
        else:
            remove.append(item['path'])
    evidence = HERE / 'evidence' / ('restore-' + uuid.uuid4().hex)
    for relative in PATHS:
        path = CLIENT / relative
        if path.exists():
            target = evidence / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    diagnostic.r3().replace_group(changes, 'Restore pre multi-minute files')
    for relative in remove:
        (CLIENT / relative).unlink(missing_ok=True)
    write_json(evidence / 'receipt.json', {'restored': PATHS, 'one_minute_original_retained': True})
    print(evidence)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['collect', 'initial', 'update', 'restore', 'build'])
    args = parser.parse_args()
    if args.action == 'collect':
        collect()
    elif args.action == 'restore':
        with bridge.Instance(HERE / 'publication-lock'):
            restore()
    elif args.action == 'build':
        batch, manifest = build(UPDATE_END)
        print(batch)
    else:
        with bridge.Instance(HERE / 'publication-lock'):
            publish(INITIAL_END if args.action == 'initial' else UPDATE_END)
