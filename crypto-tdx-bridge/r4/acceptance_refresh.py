"""Capture four independent layers while a selected chart stays open."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3
import struct
import time

from client_control import Client
from settings import load


def snapshot(config, folder, control, period, label):
    state = json.loads((control / 'state.json').read_text(encoding='utf-8'))
    database = Path(config['data_directory']) / 'market.sqlite3'
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
        bars = [dict(interval=interval, payload=json.loads(payload), final=bool(final), raw_id=raw)
                for interval in ('1m', '5m', period)
                for payload, final, raw in db.execute('SELECT payload,final,raw_id FROM bars WHERE symbol=? '
                    'AND interval=? ORDER BY open_ms DESC LIMIT 5', ('BTCUSDT', interval))]
    source = [item['payload'] for item in bars if item['interval'] == period][:5]
    path = Path(config['tdx']['data_directory']) / 'sz/fzline/sz397901.lc5'
    raw = path.read_bytes()
    last = struct.unpack_from('<HHfffffII', raw, len(raw)-32)
    captured = Client(config).capture(folder / (label + '.bmp'))
    result = {'observed_utc': datetime.now(timezone.utc).isoformat(), 'period':period,
              'network': {k:state['engine'].get(k) for k in ('connection','connection_id','last_event_ms','received')},
              'database': {'last_database_ms':state['engine'].get('last_database_ms'), 'bars':bars,
                           'source_last_five_close_mean':str(sum(Decimal(r[4]) for r in source)/len(source))},
              'file': {'last_file_ms':state['engine'].get('last_file_ms'),'sha256':hashlib.sha256(raw).hexdigest(),
                       'records':len(raw)//32,'last_lc5':last}, 'chart':captured,
              'interaction_after_initial_selection':False}
    (folder / (label + '.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--control', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--periods', nargs='+', default=['15m','30m','1h'])
    parser.add_argument('--seconds', type=float, default=25)
    args = parser.parse_args()
    config = load(args.config)
    args.output.mkdir(parents=True,exist_ok=True)
    client = Client(config)
    for period in args.periods:
        client.period(period)
        time.sleep(1)
        before=snapshot(config,args.output,args.control,period,period+'-before')
        time.sleep(args.seconds)
        after=snapshot(config,args.output,args.control,period,period+'-after')
        print(json.dumps({'period':period,'pid_unchanged':before['chart']['pid']==after['chart']['pid'],
                         'network_time_changed':before['network']['last_event_ms']!=after['network']['last_event_ms'],
                         'file_changed':before['file']['sha256']!=after['file']['sha256'],
                         'source_ma5_before':before['database']['source_last_five_close_mean'],
                         'source_ma5_after':after['database']['source_last_five_close_mean']}),flush=True)


if __name__ == '__main__': main()
