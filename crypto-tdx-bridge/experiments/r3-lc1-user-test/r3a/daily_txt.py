"""Strict, read-only native Binance daily export; no audit CSV input."""
import argparse
import datetime as dt
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3

FIELDS = {'open': 1, 'high': 2, 'low': 3, 'close': 4,
          'base_volume': 5, 'quote_amount_usdt': 7}


def convert(row):
    symbol, open_ms, close_ms, payload, raw_id = row
    data = json.loads(payload)
    if len(data) != 12 or data[0] != open_ms or data[6] != close_ms:
        raise ValueError(f'{symbol}: inconsistent native payload')
    if open_ms % 86400000 or close_ms != open_ms + 86400000 - 1:
        raise ValueError(f'{symbol}: not a UTC daily candle')
    values = []
    numbers = {}
    for name, index in FIELDS.items():
        value = data[index]
        if not isinstance(value, str) or not value or value.strip() != value:
            raise ValueError(f'{symbol}: invalid {name}')
        number = Decimal(value)
        if not number.is_finite() or number < 0:
            raise ValueError(f'{symbol}: invalid {name}')
        numbers[name] = number
        values.append(format(number, 'f'))
    if not (numbers['low'] <= min(numbers['open'], numbers['close']) <=
            max(numbers['open'], numbers['close']) <= numbers['high']):
        raise ValueError(f'{symbol}: invalid OHLC')
    date = dt.datetime.fromtimestamp(open_ms / 1000, dt.timezone.utc).strftime('%Y-%m-%d')
    return '\t'.join([date] + values), {'symbol': symbol, 'open_ms': open_ms,
                                      'raw_id': raw_id, 'payload': data}


def export(database, output):
    database = Path(database).resolve(strict=True)
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as connection:
        connection.execute('PRAGMA query_only=ON')
        rows = connection.execute("SELECT symbol,open_ms,close_ms,payload,raw_id FROM bars "
            "WHERE exchange='binance' AND market='spot' AND interval='1d' AND final=1 "
            "AND symbol IN ('BTCUSDT','ETHUSDT') ORDER BY symbol,open_ms").fetchall()
    batches = {}
    evidence = []
    for row in rows:
        line, source = convert(row)
        batches.setdefault(row[0], []).append(line)
        evidence.append(source)
    if set(batches) != {'BTCUSDT', 'ETHUSDT'}:
        raise ValueError('Both symbols require closed native daily candles')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    files = []
    for symbol, lines in batches.items():
        path = output / f'{symbol}_DAY_TDX.txt'
        # Client explicitly requires an empty last line. No header or BOM.
        content = ('\r\n'.join(lines) + '\r\n\r\n').encode('ascii')
        path.write_bytes(content)
        if [line.split('\t') for line in path.read_text().splitlines() if line] != [
                line.split('\t') for line in lines]:
            raise ValueError('Independent TXT readback mismatch')
        files.append({'path': path.name, 'rows': len(lines),
                      'sha256': hashlib.sha256(content).hexdigest()})
    after = hashlib.sha256(database.read_bytes()).hexdigest()
    if before != after:
        raise ValueError('Database changed during export')
    report = {'database': str(database), 'database_sha256': before,
              'database_unchanged': True, 'native_indices': FIELDS,
              'time': 'UTC open date', 'volume_unit': 'base asset',
              'amount_unit': 'USDT', 'files': files, 'sources': evidence,
              'precision': 'Exact decimal; client precision not yet verified'}
    (output / 'export-evidence.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--database', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(json.dumps(export(args.database, args.output), ensure_ascii=False, indent=2))
