"""Read-only UTC reference and LC1/LC5 boundary audit; no network or publication."""
import argparse
import csv
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3

from display import decode_time, encode


def utc(value):
    return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat()


def audit(database, root, output):
    if not database.is_file():
        raise FileNotFoundError(database)
    db = sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        db.execute('BEGIN')
        minute = {t: (json.loads(p), bool(f)) for t, p, f in db.execute(
            'SELECT open_ms,payload,final FROM bars WHERE symbol=? AND interval=?',
            ('BTCUSDT', '1m'))}
        native = {i: {t: (json.loads(p), bool(f)) for t, p, f in db.execute(
            'SELECT open_ms,payload,final FROM bars WHERE symbol=? AND interval=?',
            ('BTCUSDT', i))} for i in ('5m', '15m', '30m', '1h')}
        result = {'observed_utc': utc(int(datetime.now(timezone.utc).timestamp()*1000)),
                  'timezone': 'UTC', 'comparison': 'Cache bytes versus explicitly lossy display conversion; not lossless numeric equality',
                  'reference': {}, 'cache_boundaries': {}}
        for interval, count in (('5m',5), ('15m',15), ('30m',30), ('1h',60)):
            grouped = {}
            for t, value in minute.items():
                grouped.setdefault(t // (count*60000) * count*60000, []).append((t, value))
            bars = []
            for start, entries in sorted(grouped.items()):
                entries.sort()
                rows = [value[0] for _, value in entries]
                complete = len(entries) == count and all(value[1] for _,value in entries)
                values = [rows[0][1],str(max(Decimal(r[2]) for r in rows)),
                          str(min(Decimal(r[3]) for r in rows)),rows[-1][4],
                          str(sum(Decimal(r[5]) for r in rows)),str(sum(Decimal(r[7]) for r in rows))]
                n = native[interval].get(start)
                bars.append({'start_utc': utc(start),'end_exclusive_utc':utc(start+count*60000),
                    'present_minutes':len(entries),'expected_minutes':count,'complete':complete,
                    'missing_minutes_utc':[utc(t) for t in range(start,start+count*60000,60000) if t not in minute],
                    'missing_observed_range_utc':[utc(t) for t in range(start,start+count*60000,60000) if t not in minute and t <= max(minute)],
                    'not_yet_observed_minutes_utc':[utc(t) for t in range(start,start+count*60000,60000) if t not in minute and t > max(minute)],
                    'ohlc_base_quantity_usdt_amount':values,
                    'native_final': n[1] if n else None,
                    'complete_native_equal': all(Decimal(a)==Decimal(n[0][b]) for a,b in zip(values,(1,2,3,4,5,7))) if n and complete else None})
            result['reference'][interval] = bars[-16:]
            result['reference'][interval+'_first_window'] = bars[0]
        for interval,folder,suffix in (('1m','minline','lc1'),('5m','fzline','lc5')):
            path=root/'sz'/folder/('sz397901.'+suffix)
            raw=path.read_bytes()
            if len(raw)%32:
                raise ValueError('Truncated cache')
            records=[(decode_time(raw[i:i+32],False),raw[i:i+32]) for i in range(0,len(raw),32)]
            source=minute if interval=='1m' else native['5m']
            boundaries=[]
            for t,b in records[:2]+records[-16:]:
                n=source.get(t)
                boundaries.append({'open_utc':utc(t),'source_final':n[1] if n else None,
                    'matches_lossy_conversion':encode(n[0])[0]==b if n else False})
            result['cache_boundaries'][interval]={'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),
                'records':len(records),'first_utc':utc(records[0][0]),'last_utc':utc(records[-1][0]),
                'boundary_records':boundaries}
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(result,indent=2),encoding='utf-8')
        with output.with_suffix('.csv').open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.writer(stream)
            writer.writerow(['interval','start_utc','end_exclusive_utc','open','high','low','close','base_quantity','usdt_amount','present_minutes','expected_minutes','complete'])
            for interval in ('5m','15m','30m','1h'):
                for bar in result['reference'][interval]:
                    writer.writerow([interval,bar['start_utc'],bar['end_exclusive_utc'],*bar['ohlc_base_quantity_usdt_amount'],bar['present_minutes'],bar['expected_minutes'],bar['complete']])
        return result
    finally:
        db.close()


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--database',type=Path,required=True)
    p.add_argument('--quote-root',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    r=audit(a.database,a.quote_root,a.output)
    print(json.dumps({k:v[-3:] for k,v in r['reference'].items() if isinstance(v,list)},indent=2))
