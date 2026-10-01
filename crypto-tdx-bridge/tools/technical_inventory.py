"""Read-only bounded SDK/document inventory and PE export names, never loads DLLs."""
import hashlib
import json
import re
import struct
from pathlib import Path

INSTALL=Path(r'D:\Programs\tdx')
OUT=Path(__file__).resolve().parents[1]/'evidence'/'r1'/'technical'


def exports(data):
    if data[:2]!=b'MZ': return []
    pe=struct.unpack_from('<I',data,60)[0]
    machine,sections=struct.unpack_from('<HH',data,pe+4)
    optional_size=struct.unpack_from('<H',data,pe+20)[0]
    opt=pe+24
    magic=struct.unpack_from('<H',data,opt)[0]
    directory=opt+(112 if magic==0x20b else 96)
    export_rva,export_size=struct.unpack_from('<II',data,directory)
    section_start=opt+optional_size
    mapping=[]
    for n in range(sections):
        position=section_start+40*n
        virtual_size,rva,raw_size,raw=struct.unpack_from('<IIII',data,position+8)
        mapping.append((rva,max(virtual_size,raw_size),raw))
    def offset(rva):
        for base,size,raw in mapping:
            if base<=rva<base+size: return raw+rva-base
        raise ValueError('RVA outside sections')
    if not export_rva: return []
    base=offset(export_rva)
    count=struct.unpack_from('<I',data,base+24)[0]
    names=offset(struct.unpack_from('<I',data,base+32)[0])
    result=[]
    for n in range(count):
        name_start=offset(struct.unpack_from('<I',data,names+4*n)[0])
        end=data.index(b'\0',name_start)
        result.append(data[name_start:end].decode('ascii',errors='replace'))
    return result


def main():
    OUT.mkdir(parents=True,exist_ok=False)
    docs=[]; directories=[]
    suffixes={'.h','.hpp','.c','.cpp','.pdf','.chm','.md','.zip','.rar'}
    skipped={'vipdoc','T0002','chrome','jspages','TcApi_Cache','NewTc','Update'}
    for child in INSTALL.iterdir():
        if child.is_dir() and child.name in skipped:
            directories.append({'path':str(child),'content_not_searched':True,'reason':'market/account/cache or browser/update assets; no documented SDK root'})
            continue
        candidates=list(child.rglob('*')) if child.is_dir() else [child]
        for path in candidates:
            if path.is_file() and path.suffix.lower() in suffixes:
                data=path.read_bytes()
                docs.append({'path':str(path),'size':len(data),'sha256':hashlib.sha256(data).hexdigest(),'archive_not_executed':path.suffix.lower() in ('.rar','.zip')})
    for path in (INSTALL/'T0002'/'dlls').glob('*'):
        if path.is_file() and path.suffix.lower() in suffixes:
            data=path.read_bytes(); docs.append({'path':str(path),'size':len(data),'sha256':hashlib.sha256(data).hexdigest()})
    binaries=[]
    for relative in ['tdxw.exe','taapi.dll','taapix64.dll','TDataParse.dll','TCalc64.dll','TPool.dll','tdxrpc64.dll','PYPlugins/TPyth.dll','PYPlugins/TPythClient.dll','PYPlugins/tdxrpcx64.dll']:
        path=INSTALL/relative
        if not path.is_file(): continue
        data=path.read_bytes()
        binaries.append({'path':str(path),'sha256':hashlib.sha256(data).hexdigest(),'size':len(data),'exports':exports(data),'limitations':'An export name or DLL presence does not document an external OHLCV write contract.'})
    supporting=[]
    for relative in ['dsmarket.dat','ihelp.dat','idesc.dat','datatool/tools.ini','datatool/tick','datatool/newday']:
        path=INSTALL/relative
        if not path.exists(): continue
        data=path.read_bytes()
        item={'path':str(path),'sha256':hashlib.sha256(data).hexdigest(),'size':len(data)}
        if relative.startswith('datatool/'):
            target=OUT/path.name; target.write_bytes(data); item['copy']=target.name
        supporting.append(item)
    report={'installation':str(INSTALL),'scope':'static files only; no GUI, DLL loading, writes or SDK execution','document_archive_inventory':docs,'excluded_roots':directories,'binaries':binaries,'supporting_files':supporting,'external_coin_to_minute_path':'NOT_FOUND_IN_DOCUMENTED_CONTRACT','trade_session_configuration':'NOT_FOUND_IN_DOCUMENTED_CONTRACT','history_reload':'NOT_FOUND_IN_DOCUMENTED_CONTRACT'}
    (OUT/'inventory.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'documents':len(docs),'binaries':len(binaries),'document_paths':[x['path'] for x in docs],'exports':{Path(x['path']).name:x['exports'][:30] for x in binaries}},ensure_ascii=True,indent=2))


if __name__=='__main__': main()
