"""Offline review of NEW hourly boundary only; no historical test replay."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import struct
import sys

def verify(package, report):
    package=Path(package).resolve();report=Path(report).resolve()
    if report.is_relative_to(package) or report.exists():raise ValueError('Use a new report outside package')
    def audit(event,args):
        if event.startswith('socket.'):raise RuntimeError('Network is prohibited')
    sys.addaudithook(audit)
    def path(relative):
        if not isinstance(relative,str) or '\\' in relative or ':' in relative:raise ValueError('POSIX relative path required')
        selected=(package/relative).resolve()
        if Path(relative).is_absolute() or '..' in Path(relative).parts or not selected.is_relative_to(package):raise ValueError('Path escapes package')
        if not selected.is_file():raise FileNotFoundError(selected)
        return selected
    manifest=json.loads(path('MANIFEST.json').read_text(encoding='utf-8'))
    before={}
    for item in manifest['files']:
        selected=path(item['path']);digest=hashlib.sha256(selected.read_bytes()).hexdigest()
        assert selected.stat().st_size==item['bytes'] and digest==item['sha256'],item['path']
        before[item['path']]=digest
    name='NEXT-HOUR-CLOSED-VERIFIED.json' if (package/'evidence/NEXT-HOUR-CLOSED-VERIFIED.json').is_file() else 'HOUR-0700-CLOSED-VERIFIED.json'
    receipt=json.loads(path('evidence/'+name).read_text(encoding='utf-8'))
    lo=int(datetime.fromisoformat(receipt['UTC_start']).timestamp()*1000)
    hi=int(datetime.fromisoformat(receipt['UTC_end_exclusive']).timestamp()*1000)
    db=sqlite3.connect(path('evidence/market-snapshot.sqlite3').as_uri()+'?mode=ro&immutable=1',uri=True)
    try:
        rows=list(db.execute("SELECT payload,final,raw_id FROM bars WHERE symbol='ETHUSDT' AND interval='5m' AND open_ms>=? AND open_ms<? ORDER BY open_ms",(lo,hi)))
        native=db.execute("SELECT payload,final,raw_id FROM bars WHERE symbol='ETHUSDT' AND interval='1h' AND open_ms=?",(lo,)).fetchone()
    finally:db.close()
    assert len(rows)==12 and all(r[1] for r in rows) and native and native[1]
    parts=[json.loads(row[0]) for row in rows]
    assert [p[0] for p in parts]==list(range(lo,hi,300000))
    raw_checked=0
    for (payload,final,identity) in rows+[native]:
        exact=json.loads(payload)
        if re.fullmatch('ws-[0-9a-f]{32}',identity):
            event=json.loads(path('evidence/raw/ws/'+identity+'.json').read_text(encoding='utf-8'))
            data=event.get('data',event);k=data['k']
            recovered=[k['t'],k['o'],k['h'],k['l'],k['c'],k['v'],k['T'],k['q'],k['n'],k['V'],k['Q'],k.get('B','0')]
            assert recovered==exact and k['x'] is True and k['s']=='ETHUSDT'
        elif re.fullmatch('[0-9a-f]{32}',identity):
            raw=json.loads(path('evidence/raw/'+identity+'.body').read_bytes())
            assert exact in raw
        else:raise ValueError('Unexpected raw identity')
        raw_checked+=1
    summary=[Decimal(parts[0][1]),max(Decimal(p[2]) for p in parts),min(Decimal(p[3]) for p in parts),Decimal(parts[-1][4]),
             sum((Decimal(p[5]) for p in parts),Decimal(0)),sum((Decimal(p[7]) for p in parts),Decimal(0))]
    assert summary==[Decimal(json.loads(native[0])[i]) for i in (1,2,3,4,5,7)]
    converted=[]
    actual_records={}
    if name=='NEXT-HOUR-CLOSED-VERIFIED.json':
        binary=path('evidence/NEXT-HOUR-ACTUAL-LC5.lc5').read_bytes()
        assert len(binary)==12*32
        for offset in range(0,len(binary),32):
            record=binary[offset:offset+32]
            day,minute=struct.unpack_from('<HH',record)
            year=2004+day//2048;calendar=day%2048
            assert minute%5==4
            midnight=datetime(year,calendar//100,calendar%100,tzinfo=timezone.utc)
            key=int(midnight.timestamp()*1000)+(minute-4)*60000
            assert key not in actual_records
            actual_records[key]=record
    for p,record in zip(parts,receipt['records']):
        moment=datetime.fromtimestamp((p[0]+240000)/1000,timezone.utc)
        binary=struct.pack('<HHfffffII',(moment.year-2004)*2048+moment.month*100+moment.day,moment.hour*60+moment.minute,
            *(float(p[i]) for i in (1,2,3,4,7)),int(Decimal(p[5])),0)
        assert binary.hex()==record['record_hex']
        if actual_records:
            assert actual_records[p[0]]==binary,'Actual cache snapshot differs from converted exact source'
        converted.append(struct.unpack('<HHfffffII',binary))
    cache_ohlc=[converted[0][2],max(r[3] for r in converted),min(r[4] for r in converted),converted[-1][5]]
    assert all(abs(a-b)<.000006 for a,b in zip(cache_ohlc,receipt['client_OHLC']))
    assert all(hashlib.sha256(path(name).read_bytes()).hexdigest()==digest for name,digest in before.items())
    result={'status':'passed_with_scope','scope':'new closed hourly boundary only; no historical revalidation',
        'files_verified':len(before),'raw_records_verified':raw_checked,'database_read_only':True,'zero_network':True,
        'input_hashes_unchanged':True,'hour_UTC_start':receipt['UTC_start'],'final_LC5_records':12,
        'client_OHLC_matches_existing_lossy_conversion':True,'actual_cache_snapshot_verified':bool(actual_records),
        'automatic_append':'see separate passive observation receipt',
        'accuracy_acceptance':False,'product_status':'PARTIAL'}
    report.parent.mkdir(parents=True,exist_ok=True)
    report.write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--package',required=True);parser.add_argument('--report',required=True)
    args=parser.parse_args();verify(args.package,args.report)
