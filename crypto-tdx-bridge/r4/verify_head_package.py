"""Offline head-window review; package inputs read only, report outside package."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
import sqlite3
import struct
import sys


def verify(package, report):
    package=Path(package).resolve(strict=True)
    report=Path(report).resolve()
    if report.is_relative_to(package):
        raise ValueError('Report must be outside the hashed package')
    sys.addaudithook(lambda event,args: (_ for _ in ()).throw(RuntimeError('Network prohibited'))
                     if event.startswith('socket.') else None)
    manifest=json.loads((package/'MANIFEST.json').read_text(encoding='utf-8'))
    def hashes():
        result={}
        for item in manifest['files']:
            rel=PurePosixPath(item['path'])
            if rel.is_absolute() or '..' in rel.parts or '\\' in item['path'] or ':' in item['path']:
                raise ValueError('Unsafe package path')
            p=(package/rel).resolve(strict=True)
            if not p.is_relative_to(package):
                raise ValueError('Package path escaped root')
            digest=hashlib.sha256(p.read_bytes()).hexdigest()
            if digest!=item['sha256']:
                raise ValueError('SHA-256 mismatch: '+item['path'])
            result[item['path']]=digest
        return result
    before=hashes()
    database=(package/'evidence/market-snapshot.sqlite3').resolve(strict=True)
    db=sqlite3.connect(database.as_uri()+'?mode=ro&immutable=1',uri=True)
    try:
        rows={t:json.loads(p) for t,p in db.execute(
            "SELECT open_ms,payload FROM bars WHERE symbol='ETHUSDT' AND interval='5m' AND final=1")}
        start=int(datetime(2026,9,29,23,tzinfo=timezone.utc).timestamp()*1000)
        prefix=list(db.execute("SELECT payload,raw_id FROM bars WHERE open_ms>=? AND open_ms<? AND interval IN ('1m','5m')",(start,start+3600000)))
        assert len(prefix)==216
        raw_cache={}
        for payload,identity in prefix:
            if not isinstance(identity,str) or not re.fullmatch('[0-9a-f]{32}',identity):
                raise ValueError('Unsafe raw-response reference')
            if identity not in raw_cache:
                body=package/'evidence/raw'/(identity+'.body')
                raw_cache[identity]=json.loads(body.read_bytes())
            row=json.loads(payload)
            assert row in raw_cache[identity], 'Exact prefix row differs from raw response'
    finally:
        db.close()
    checks=[]
    f32=lambda value:struct.unpack('<f',struct.pack('<f',float(value)))[0]
    for interval,size in [('15m',15),('30m',30),('1h',60)]:
        observation=json.loads((package/f'evidence/prefix-ETH-{interval}.json').read_text(encoding='utf-8'))
        unique={r['1354']:r for r in observation['rows']}
        earliest=min(unique,key=lambda s:s[:8]+s[-5:])
        expected=datetime(2026,9,29,23,tzinfo=timezone.utc)+timedelta(minutes=size-1)
        assert earliest[:8]=='26/09/29' and earliest[-5:]==expected.strftime('%H:%M')
        for label,value in unique.items():
            if label[:8] not in ('26/09/29','26/09/30') or label[-5:] not in ('23:14','23:29','23:59','00:14','00:29','00:59'):
                continue
            end=datetime.strptime(label[:8]+' '+label[-5:],'%y/%m/%d %H:%M').replace(tzinfo=timezone.utc)+timedelta(minutes=1)
            start=end-timedelta(minutes=size)
            parts=[rows[int((start+timedelta(minutes=i)).timestamp()*1000)] for i in range(0,size,5)]
            converted=[f32(parts[0][1]),max(f32(p[2]) for p in parts),min(f32(p[3]) for p in parts),f32(parts[-1][4])]
            actual=[float(value[str(i)].split('(')[0]) for i in (1356,1357,1358,1359)]
            assert all(abs(a-b)<.000006 for a,b in zip(converted,actual)),(interval,label)
            checks.append({'interval':interval,'label':label,'source_UTC_start':start.isoformat(),'LC5_count':len(parts)})
    assert len(checks)>=9
    assert hashes()==before,'Inputs changed'
    receipt={'offline_review':'passed_with_scope','package_files_verified':len(before),'zero_network':True,
             'raw_exact_prefix_rows_verified':len(prefix),
             'database_read_only':True,'input_hashes_unchanged':True,'head_window_checks':checks,
             'comparison':'lossy float32 OHLC versus five-decimal client display; not volume accuracy or automatic refresh',
             'product_status':'PARTIAL'}
    report.parent.mkdir(parents=True,exist_ok=True)
    if report.exists():
        raise FileExistsError('Do not overwrite review receipt')
    report.write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print(json.dumps(receipt))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--package',required=True)
    parser.add_argument('--report',required=True)
    args=parser.parse_args()
    verify(args.package,args.report)
