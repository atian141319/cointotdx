"""R3 display-only LC1 trial. Never imports or changes the signed collector."""
import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import sqlite3
import struct
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

HERE=Path(__file__).resolve().parent
PROJECT=HERE.parents[1]
INSTALL=Path('D:/Programs/tdx')
CLIENT=HERE/'client'
BASELINE=HERE/'backup'/'client-before-trial'
LAYOUT=struct.Struct('<HHfffffII')
PAIRS={'BTCUSDT':'999006','ETHUSDT':'999007'}
EXCLUDED={'vipdoc','datatool','T0001','T0002','Update','TcApi_Cache'}
SNAPSHOT=PROJECT/'artifacts/CRYPTO-TDX-R1A-20261001T034113542138Z/staged/crypto-tdx-bridge/evidence/r1a/market-snapshot.sqlite3'


def sha(data): return hashlib.sha256(data).hexdigest()
def write_json(path,value): path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
def inventory(root):
    return {p.relative_to(root).as_posix():{'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size}
            for p in root.rglob('*') if p.is_file()}


def no_client():
    if os.name!='nt': raise RuntimeError('Client operations require Windows')
    command="@(Get-CimInstance Win32_Process -Filter \"Name='tdxw.exe'\" | Select-Object ProcessId,ExecutablePath) | ConvertTo-Json -Compress"
    result=subprocess.run(['powershell','-NoProfile','-Command',command],capture_output=True,text=True,encoding='utf-8',check=True)
    raw=result.stdout.strip()
    processes=json.loads(raw) if raw not in ('','[]','null') else []
    if isinstance(processes,dict): processes=[processes]
    for process in processes:
        executable=process.get('ExecutablePath')
        if not executable or Path(executable).resolve().is_relative_to(CLIENT.resolve()):
            raise RuntimeError('请先正常关闭隔离副本通达信窗口，不会强杀进程: '+raw)


def pack_row(row):
    stamp=datetime.fromtimestamp(row[0]/1000,timezone.utc)
    day=(stamp.year-2004)*2048+stamp.month*100+stamp.day
    if not 0<=day<=65535 or row[0]%60000: raise ValueError('Date/minute out of range')
    values=[]; errors={}
    for name,index in (('open',1),('high',2),('low',3),('close',4),('quote_amount',7)):
        original=Decimal(row[index]); candidate=struct.unpack('<f',struct.pack('<f',float(original)))[0]
        if not math.isfinite(candidate): raise ValueError('float32 overflow')
        exact=Decimal.from_float(candidate); diff=exact-original
        values.append(candidate)
        errors[name]={'original':str(original),'written_float32_exact':str(exact),
                      'signed_rounding_error':str(diff),'absolute_error':str(abs(diff))}
    volume=Decimal(row[5])
    if not volume.is_finite() or volume<0: raise ValueError('Invalid volume')
    integer=int(volume)  # Explicit R3 authorization: truncate only the trial representation.
    if integer>0xffffffff: raise ValueError('uint32 volume overflow; no further scaling allowed')
    data=LAYOUT.pack(day,stamp.hour*60+stamp.minute,*values,integer,0)
    return data,{'utc_open':stamp.isoformat(),'open_ms':row[0],'float_fields':errors,
                 'volume':{'original_base_quantity':str(volume),'written_u32':integer,
                           'written_minus_original':str(Decimal(integer)-volume),
                           'truncated_quantity':str(volume-Decimal(integer)),
                           'positive_quantity_became_zero':volume>0 and integer==0},
                 'tail':{'written_u32':0,'semantics':'试验假设，语义未确认'},
                 'time_label':'UTC opening minute; client interpretation unverified'}


def generate():
    if not SNAPSHOT.is_file(): raise FileNotFoundError(SNAPSHOT)
    output=HERE/'samples'; output.mkdir(exist_ok=False)
    con=sqlite3.connect(SNAPSHOT.as_uri()+'?mode=ro&immutable=1',uri=True)
    reports=[]; expected=[]
    try:
        for symbol,code in PAIRS.items():
            source=con.execute("SELECT payload,raw_id FROM bars WHERE exchange='binance' AND market='spot' AND symbol=? AND interval='1m' AND final=1 ORDER BY open_ms",(symbol,)).fetchall()
            if len(source)!=10: raise ValueError('Expected exactly 10 sealed real sample bars')
            records=[]
            for payload,raw_id in source:
                row=json.loads(payload); encoded,report=pack_row(row); records.append(encoded)
                report.update(symbol=symbol,test_code=code,raw_id=raw_id,display_name=symbol+'显示试验')
                reports.append(report)
                decoded=LAYOUT.unpack(encoded)
                expected.append({'symbol':symbol,'code':code,'utc_open':report['utc_open'],
                                 'batch':'initial+update' if len(records)<=8 else 'update-only',
                                 'original_close':row[4],'written_close_exact':str(Decimal.from_float(decoded[5])),
                                 'original_volume':row[5],'written_integer_volume':decoded[7]})
            for batch,count in (('initial',8),('update',10)):
                folder=output/batch; folder.mkdir(exist_ok=True)
                (folder/('sh'+code+'.lc1')).write_bytes(b''.join(records[:count]))
    finally: con.close()
    write_json(output/'representation-errors.json',{'display_trial_only':True,
               'source_snapshot_sha256':sha(SNAPSHOT.read_bytes()),'production_accuracy_approved':False,'rows':reports})
    with (output/'expected-display.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(expected[0])); writer.writeheader(); writer.writerows(expected)
    write_json(output/'sample-manifest.json',inventory(output))


def conflicts():
    locations=[INSTALL/'T0002/hq_cache',INSTALL/'T0002/ds_cache',INSTALL/'T0002/blocknew']
    scanned=[]; found=[]
    for directory in locations:
        for p in directory.rglob('*'):
            if not p.is_file(): continue
            # Code registries and user lists: exact ASCII token hits fail closed.
            if p.suffix.lower() not in ('.tnf','.dat','.cfg','.ini','.blk','.txt','.tcu','.tfz'): continue
            data=p.read_bytes(); scanned.append({'source':str(p),'sha256':sha(data)})
            for symbol,code in PAIRS.items():
                if code.encode() in data: found.append({'code':code,'path':str(p),'reason':'existing code token'})
    for code in PAIRS.values():
        for p in (INSTALL/'vipdoc').rglob('*'+code+'*'):
            found.append({'code':code,'path':str(p),'reason':'existing market file name'})
    write_json(HERE/'evidence'/'code-conflicts.json',{'codes':PAIRS,'scanned':scanned,'hits':found})
    if found: raise RuntimeError('Test code collision; no files overwritten: '+str(found))


def copy_runtime():
    BASELINE.mkdir(parents=True,exist_ok=False)
    sources=[]
    for p in INSTALL.iterdir():
        if p.name in EXCLUDED: continue
        candidates=list(p.rglob('*')) if p.is_dir() else [p]
        for f in candidates:
            if not f.is_file(): continue
            if f.is_symlink() or (hasattr(f,'is_junction') and f.is_junction()): raise ValueError('No linked client files allowed')
            rel=f.relative_to(INSTALL); dest=BASELINE/rel; dest.parent.mkdir(parents=True,exist_ok=True)
            original=f.read_bytes(); dest.write_bytes(original)
            sources.append({'source':str(f),'destination':dest.relative_to(HERE).as_posix(),'sha256':sha(original)})
    for directory in ('hq_cache','ds_cache','dlls','blocknew'):
        for f in (INSTALL/'T0002'/directory).rglob('*'):
            if not f.is_file(): continue
            if f.is_symlink() or (hasattr(f,'is_junction') and f.is_junction()): raise ValueError('No linked cache files allowed')
            dest=BASELINE/f.relative_to(INSTALL); dest.parent.mkdir(parents=True,exist_ok=True)
            data=f.read_bytes(); dest.write_bytes(data)
            sources.append({'source':str(f),'destination':dest.relative_to(HERE).as_posix(),'sha256':sha(data)})
    (BASELINE/'T0002').mkdir(exist_ok=True)
    write_json(HERE/'evidence'/'copy-sources.json',sources)
    write_json(HERE/'evidence'/'baseline-manifest.json',inventory(BASELINE))
    shutil.copytree(BASELINE,CLIENT)


def replace_group(changes,label):
    no_client()
    transaction=HERE/'transactions'/str(uuid.uuid4()); transaction.mkdir(parents=True)
    entries=[]; staged=[]
    for rel,data in changes.items():
        dest=CLIENT/rel
        if not dest.resolve().is_relative_to(CLIENT.resolve()): raise ValueError('Client path escape')
        dest.parent.mkdir(parents=True,exist_ok=True)
        old=dest.read_bytes() if dest.exists() else None
        backup=transaction/rel; backup.parent.mkdir(parents=True,exist_ok=True)
        if old is not None: backup.write_bytes(old)
        entries.append({'path':rel,'existed_before':old is not None,'before_sha256':sha(old) if old is not None else None,
                        'after_sha256':sha(data),'backup':backup.relative_to(HERE).as_posix() if old is not None else None})
        temp=dest.with_name(dest.name+'.'+transaction.name+'.tmp')
        with temp.open('wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        staged.append((dest,temp,old))
    write_json(transaction/'changes.json',{'batch_id':transaction.name,'label':label,'state':'PREPARED','files':entries})
    done=[]
    try:
        no_client()
        for dest,temp,old in staged: os.replace(temp,dest); done.append((dest,old))
    except Exception:
        for dest,old in reversed(done):
            if old is None: dest.unlink(missing_ok=True)
            else:
                rollback=dest.with_suffix(dest.suffix+'.rollback'); rollback.write_bytes(old); os.replace(rollback,dest)
        raise
    finally:
        for dest,temp,old in staged: temp.unlink(missing_ok=True)
    write_json(transaction/'changes.json',{'batch_id':transaction.name,'label':label,'state':'COMMITTED','files':entries})
    return entries


def register():
    rel='T0002/hq_cache/shs.tnf'; data=(CLIENT/rel).read_bytes()
    if (len(data)-50)%360: raise ValueError('Observed TNF 50-byte header/360-byte records mismatch')
    records=[data[i:i+360] for i in range(50,len(data),360)]
    identities={r[:6] for r in records}
    additions=[]
    for symbol,code in PAIRS.items():
        if code.encode() in identities: raise ValueError('Existing registered code collision')
        record=bytearray(360)
        record[:6]=code.encode('ascii')
        name=(symbol+'显示试验').encode('gbk')
        if len(name)>20: raise ValueError('Trial name too long')
        record[31:31+len(name)]=name
        record[327:327+len(symbol)]=symbol.encode('ascii')
        additions.append(bytes(record))
    replace_group({rel:data+b''.join(additions)},'candidate-name-registration')
    write_json(HERE/'evidence'/'registration-attempt.json',{'market':'SH / candidate market 1',
               'identity_cache':'T0002/hq_cache/shs.tnf','observed_record_layout':'50-byte header, 360-byte records; names at offset31',
               'registration':'candidate cache records written; client recognition must be observed',
               'format_contract':'UNCONFIRMED trial hypothesis; no existing stock record copied or renamed',
               'pairs':[{'symbol':s,'code':c,'name':s+'显示试验'} for s,c in PAIRS.items()]})


def register_associations():
    """Second bounded trial hypothesis; no stock identities, quotes or binaries copied."""
    no_client()
    registry_path='T0002/hq_cache/shs.tnf'
    data=bytearray((CLIENT/registry_path).read_bytes())
    original=(BASELINE/registry_path).read_bytes()
    count=(len(original)-50)//360
    if len(data)!=len(original)+720: raise ValueError('Unexpected candidate registry size')
    observations=[]
    for number,(symbol,code) in enumerate(PAIRS.items()):
        offset=len(original)+number*360
        if data[offset:offset+6]!=code.encode(): raise ValueError('Trial registry identity changed')
        observations.append({'code':code,'name':symbol+'显示试验',
                             'unknown_metadata':'left unchanged; no guessed price/volume unit factors'})
    changes={registry_path:bytes(data)}
    for name,width in (('sh.tcu',154),('sh.th2',516),('sh.tfz',5)):
        rel='T0002/hq_cache/'+name; old=(BASELINE/rel).read_bytes()
        if len(old)!=count*width: raise ValueError('Native parallel cache length mismatch')
        changes[rel]=old+bytes(2*width)
    replace_group(changes,'candidate-parallel-cache-association')
    write_json(HERE/'evidence'/'registration-association-attempt.json',{
        'native_tnf_records':count,'parallel_cache_candidate_record_bytes':{'sh.tcu':154,'sh.th2':516,'sh.tfz':5},
        'metadata_trial':observations,'client_recognition':'UNVERIFIED',
        'hypothesis':'align copied native parallel cache record counts with two new independent trial identities',
        'no_existing_security_identity_reused':True,'stock_data_files_overwritten':False})


def publish(batch):
    no_client()
    registry=(CLIENT/'T0002/hq_cache/shs.tnf').read_bytes()
    for symbol,code in PAIRS.items():
        matches=[registry[i:i+360] for i in range(50,len(registry),360) if registry[i:i+6]==code.encode()]
        if len(matches)!=1 or (symbol+'显示试验').encode('gbk') not in matches[0]:
            raise ValueError('Candidate test identity missing or changed; refusing stock overwrite')
    changes={'vipdoc/sh/minline/sh'+code+'.lc1':(HERE/'samples'/batch/('sh'+code+'.lc1')).read_bytes() for code in PAIRS.values()}
    entries=replace_group(changes,'LC1-'+batch)
    write_json(HERE/'evidence'/('published-'+batch+'.json'),{'batch':batch,'client_closed_at_write':True,'files':entries,'display_verified':False})


def restore():
    no_client()
    if CLIENT.resolve()!=HERE.resolve()/'client' or BASELINE.resolve()!=HERE.resolve()/'backup'/'client-before-trial':
        raise ValueError('Invalid restore scope')
    baseline=json.loads((HERE/'evidence'/'baseline-manifest.json').read_text(encoding='utf-8'))
    if inventory(BASELINE)!=baseline: raise ValueError('Baseline backup changed; cannot restore')
    current=inventory(CLIENT)
    write_json(HERE/'evidence'/('before-restore-'+uuid.uuid4().hex+'.json'),current)
    for rel in current.keys()-baseline.keys():
        target=CLIENT/rel
        if not target.resolve().is_relative_to(CLIENT.resolve()): raise ValueError('Restore path escape')
        target.unlink()
    for rel,info in baseline.items():
        if current.get(rel)!=info:
            dest=CLIENT/rel; dest.parent.mkdir(parents=True,exist_ok=True)
            temp=dest.with_name(dest.name+'.restore.tmp'); shutil.copy2(BASELINE/rel,temp); os.replace(temp,dest)
    if inventory(CLIENT)!=baseline: raise ValueError('Restore verification failed')
    write_json(HERE/'evidence'/('restored-'+uuid.uuid4().hex+'.json'),{'client_files_equal_to_baseline':True,'original_install_modified':False})
    print('已恢复隔离副本到试验前状态；原安装未改动。样本、备份、变更日志保留。')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','initial','update','restore','status','associate'])
    args=parser.parse_args()
    if args.action=='prepare':
        no_client()
        if CLIENT.exists() or BASELINE.exists() or (HERE/'samples').exists(): raise ValueError('Trial already prepared; use initial/update/restore')
        (HERE/'evidence').mkdir(exist_ok=True)
        previous=HERE/'evidence'/'code-conflicts.json'
        if previous.exists(): previous.rename(previous.with_name('code-conflicts-attempt-'+uuid.uuid4().hex+'.json'))
        conflicts(); generate(); copy_runtime(); register(); publish('initial')
        print('初始批已写入隔离副本。注册与显示仍待实机观察。')
    elif args.action in ('initial','update'): publish(args.action); print('写入完成，请启动副本查看；刷新采用关闭后重启试验。')
    elif args.action=='restore': restore()
    elif args.action=='associate': register_associations()
    else:
        print(json.dumps({'client':str(CLIENT),'codes':PAIRS,'lc1_files':{c:(CLIENT/'vipdoc/sh/minline'/('sh'+c+'.lc1')).stat().st_size if (CLIENT/'vipdoc/sh/minline'/('sh'+c+'.lc1')).exists() else None for c in PAIRS.values()},'registration_and_display':'UNVERIFIED unless GUI evidence states otherwise'},indent=2))


if __name__=='__main__': main()
