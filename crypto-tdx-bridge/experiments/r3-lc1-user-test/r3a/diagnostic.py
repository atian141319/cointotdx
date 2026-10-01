"""R3A: same independent codes, native daily chart control, frozen A/B/C minute controls."""
import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
import struct
import subprocess
import uuid
from datetime import datetime
from pathlib import Path

HERE=Path(__file__).resolve().parent
TRIAL=HERE.parent
CLIENT=TRIAL/'client'
PROJECT=TRIAL.parents[1]
LC1=struct.Struct('<HHfffffII')
DAY=struct.Struct('<IIIIIfII')
CODES=('999006','999007')
REGISTRY='T0002/hq_cache/shs.tnf'
CONFIGS=(REGISTRY,'T0002/hq_cache/sh.tcu','T0002/hq_cache/sh.th2','T0002/hq_cache/sh.tfz',
         'T0002/user.ini','connect.cfg')
DATA=tuple('vipdoc/sh/'+folder+'/sh'+code+'.'+ext for code in CODES
           for folder,ext in (('minline','lc1'),('lday','day'),('fzline','lc5')))


def sha(data): return hashlib.sha256(data).hexdigest()
def write_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def closed():
    # CIM fails closed when the execution sandbox hides or denies process access.
    result=subprocess.run(['powershell','-NoProfile','-Command',"@(Get-CimInstance Win32_Process -Filter \"Name='tdxw.exe'\" -ErrorAction Stop).Count"],capture_output=True,text=True,check=True)
    if result.stdout.strip()!='0': raise RuntimeError('请正常关闭所有通达信窗口；不会强杀或运行中写入')


def r3():
    spec=importlib.util.spec_from_file_location('r3_trial',TRIAL/'experiment.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    # Keep R3 untouched; use this driver's all-client-closed guard for transactions.
    module.no_client=closed
    return module


def minute_report(data):
    if len(data)%32: raise ValueError('LC1 length not divisible by 32')
    rows=list(LC1.iter_unpack(data)); observed=[]
    for index,row in enumerate(rows):
        encoded,minute,o,h,l,c,amount,volume,tail=row
        year=encoded//2048+2004; md=encoded%2048
        date=datetime(year,md//100,md%100)
        if not 0<=minute<1440 or not all(math.isfinite(v) for v in (o,h,l,c,amount)) or not l<=min(o,c)<=max(o,c)<=h:
            raise ValueError('Invalid native/candidate record')
        observed.append({'index':index,'unzoned_time':date.strftime('%Y-%m-%d')+'T'+f'{minute//60:02d}:{minute%60:02d}:00',
                         'weekday':date.weekday(),'date_u16':encoded,'minute_u16':minute,
                         'open':o,'high':h,'low':l,'close':c,'amount_f32':amount,
                         'volume_u32':volume,'tail_u32':tail,'tail_hex':data[index*32+28:index*32+32].hex()})
    return {'bytes':len(data),'records':len(rows),'sha256':sha(data),'rows':observed}


def audit():
    data=(CLIENT/REGISTRY).read_bytes()
    count,remainder=divmod(len(data)-50,360)
    if remainder: raise ValueError('TNF record alignment')
    identities=[]
    for code in CODES:
        matches=[(index,data[50+index*360:50+(index+1)*360]) for index in range(count)
                 if data[50+index*360:56+index*360]==code.encode()]
        if len(matches)!=1: raise ValueError('Missing/duplicate trial identity')
        index,record=matches[0]
        identities.append({'code':code,'market':'SH candidate market1: shs.tnf + sh file prefix',
            'tnf_index':index,'name':record[31:51].split(b'\0')[0].decode('gbk'),
            'type':'UNCONFIRMED; search recognition does not establish instrument type',
            'offset76_u8':record[76],'offset78_f32':struct.unpack_from('<f',record,78)[0],
            'raw_record_sha256':sha(record),'record_hex':record.hex()})
    files=[]
    for rel in CONFIGS+DATA:
        p=CLIENT/rel;entry={'path':rel,'exists':p.is_file()}
        if p.is_file():
            raw=p.read_bytes();entry.update(bytes=len(raw),sha256=sha(raw))
            if p.suffix=='.lc1':entry['readback']=minute_report(raw)
            if p.suffix=='.day':
                if len(raw)%32:raise ValueError('DAY length alignment')
                rows=list(DAY.iter_unpack(raw))
                entry.update(candidate_day_records=len(rows),first_record=rows[0] if rows else None,last_record=rows[-1] if rows else None)
        files.append(entry)
    parallel=[]
    for file,width in (('sh.tcu',154),('sh.th2',516),('sh.tfz',5)):
        length=(CLIENT/'T0002/hq_cache'/file).stat().st_size
        parallel.append({'path':'T0002/hq_cache/'+file,'candidate_record_bytes':width,
                         'records':length//width,'remainder':length%width,'matches_tnf_count':length==count*width})
    return {'client_executable':str(CLIENT/'tdxw.exe'),'tnf_records':count,'identities':identities,
            'parallel_caches':parallel,'files':files,'gui_user_observation':'User confirms both codes searchable; no K-line window',
            'official_type_contract_verified':False}


def prepare():
    closed()
    if (HERE/'backup/manifest.json').exists():raise RuntimeError('Prepared already; no overwrite')
    before=audit();write_json(HERE/'evidence/before-audit.json',before)
    backup=[]
    for rel in CONFIGS+DATA:
        source=CLIENT/rel;exists=source.is_file()
        entry={'path':rel,'existed_before':exists,'sha256':sha(source.read_bytes()) if exists else None}
        if exists:
            destination=HERE/'backup'/rel;destination.parent.mkdir(parents=True,exist_ok=True)
            destination.write_bytes(source.read_bytes())
        backup.append(entry)
    write_json(HERE/'backup/manifest.json',backup)
    original=PROJECT/'validation/lc1-p0/native/sh600000.lc1'
    native=original.read_bytes()
    (HERE/'samples').mkdir(exist_ok=False)
    # Native control remains byte-for-byte intact, including all tail fields.
    native_day=Path('D:/Programs/tdx/vipdoc/sh/lday/sh600000.day')
    day=native_day.read_bytes()
    if not day or len(day)%32:raise ValueError('Native day control unavailable')
    (HERE/'samples/native-day-control.day').write_bytes(day)
    references={'native_minute':{'source':str(original),'sha256':sha(native)},
                'native_day':{'source':str(native_day),'sha256':sha(day),'bytes':len(day),'records':len(day)//32},
                'A':'原生数据格式对照：原始 SH600000 LC1 全文件，非币行情',
                'B':'人为改时的诊断数据：仅改日期/分钟为2026-06-08周一09:31–09:40；其余28字节原样',
                'C':'真实UTC周末午夜BTC/ETH显示试验，保留R3试验量价表示'}
    for group in ('A','B','C'):
        folder=HERE/'samples'/group;folder.mkdir()
        for code in CODES:
            real=(TRIAL/'samples/update'/('sh'+code+'.lc1')).read_bytes()
            if group=='A':candidate=native
            elif group=='C':candidate=real
            else:
                candidate=bytearray(real)
                encoded=(2026-2004)*2048+6*100+8
                for index in range(len(real)//32):struct.pack_into('<HH',candidate,index*32,encoded,571+index)
                candidate=bytes(candidate)
                if any(candidate[i+4:i+32]!=real[i+4:i+32] for i in range(0,len(real),32)):raise ValueError('B changed non-time bytes')
            (folder/('sh'+code+'.lc1')).write_bytes(candidate)
            write_json(folder/('sh'+code+'.readback.json'),minute_report(candidate))
    write_json(HERE/'samples/references.json',references)
    print('R3A current-state backup and A/B/C prepared; no live client files changed.')


def names(group):
    data=bytearray((CLIENT/REGISTRY).read_bytes())
    label={'D':'原生日线对照','A':'原生格式对照','B':'人为改时诊断','C':'真实时间试验'}[group]
    for code in CODES:
        offsets=[i for i in range(50,len(data),360) if data[i:i+6]==code.encode()]
        if len(offsets)!=1:raise ValueError('Trial identity missing/duplicate')
        offset=offsets[0];name=(('BTC' if code=='999006' else 'ETH')+label).encode('gbk')
        if len(name)>20:raise ValueError('Display label too long')
        data[offset+31:offset+51]=name.ljust(20,b'\0')
    return bytes(data)


def apply(group):
    closed()
    if not (HERE/'backup/manifest.json').exists():raise RuntimeError('Run prepare first')
    # Use the same two market-1 identities as the selected rows; no dependence
    # on keyboard search or the user's original installation/watch list.
    watchlist='T0002/blocknew/zxg.blk'
    extra_manifest=HERE/'backup/extra-manifest.json'
    if not extra_manifest.exists():
        source=CLIENT/watchlist;data=source.read_bytes() if source.exists() else None
        if data is not None:
            destination=HERE/'backup'/watchlist;destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(data)
        write_json(extra_manifest,[{'path':watchlist,'existed_before':data is not None,'sha256':sha(data) if data is not None else None}])
    changes={REGISTRY:names(group),watchlist:b'1999006\r\n1999007\r\n'}
    native_day=(HERE/'samples/native-day-control.day').read_bytes()
    for code in CODES:
        changes['vipdoc/sh/lday/sh'+code+'.day']=native_day
        if group!='D':changes['vipdoc/sh/minline/sh'+code+'.lc1']=(HERE/'samples'/group/('sh'+code+'.lc1')).read_bytes()
    transaction=r3().replace_group(changes,'R3A-'+group)
    receipt={'group':group,'native_day_control_common_to_all_groups':True,'changes':transaction,
             'after_audit':audit(),'gui_result':'NOT_OBSERVED','diagnostic_only':True}
    destination=HERE/'evidence'/('applied-'+group+'-'+uuid.uuid4().hex+'.json');write_json(destination,receipt)
    write_json(HERE/'active.json',{'group':group,'receipt':destination.relative_to(HERE).as_posix()})
    print('R3A '+group+' written while closed; hashes/readback recorded. Start isolated client and view chart.')


def restore():
    closed()
    manifest=json.loads((HERE/'backup/manifest.json').read_text(encoding='utf-8'))
    if (HERE/'backup/extra-manifest.json').exists():
        manifest+=json.loads((HERE/'backup/extra-manifest.json').read_text(encoding='utf-8'))
    changes={};remove=[]
    for entry in manifest:
        rel=entry['path'];dest=CLIENT/rel
        if not dest.resolve().is_relative_to(CLIENT.resolve()):raise ValueError('Restore scope violation')
        if entry['existed_before']:
            data=(HERE/'backup'/rel).read_bytes()
            if sha(data)!=entry['sha256']:raise ValueError('Backup hash mismatch')
            changes[rel]=data
        elif dest.exists():remove.append(dest)
    r3().replace_group(changes,'R3A-restore-existing')
    closed()
    for dest in remove:dest.unlink()
    for entry in manifest:
        p=CLIENT/entry['path']
        if p.exists()!=entry['existed_before'] or (p.exists() and sha(p.read_bytes())!=entry['sha256']):raise ValueError('Restore mismatch')
    write_json(HERE/'evidence'/('restore-'+uuid.uuid4().hex+'.json'),{'exact_target_files_restored':True,'original_install_modified':False})
    print('已恢复 R3A 前的试验文件和配置；保留 R3 已注册的测试品种。')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=('prepare','audit','D','A','B','C','restore'))
    args=p.parse_args()
    if args.action=='prepare':prepare()
    elif args.action=='audit':
        report=audit();write_json(HERE/'evidence'/('audit-'+uuid.uuid4().hex+'.json'),report)
        print(json.dumps({k:v for k,v in report.items() if k!='files'},ensure_ascii=True,indent=2))
    elif args.action=='restore':restore()
    else:apply(args.action)


if __name__=='__main__':main()
