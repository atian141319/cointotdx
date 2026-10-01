"""Download referenced official documents and inspect SDK headers without loading code."""
import hashlib
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import quote, urljoin
from urllib.request import Request, build_opener, ProxyHandler

ROOT=Path(__file__).resolve().parents[1]
TECH=ROOT/'evidence'/'r1'/'technical'
OUT=TECH/'official-sdk-bounded'

def main():
    OUT.mkdir(parents=True,exist_ok=False)
    findings=json.loads((TECH/'manual-findings.json').read_text(encoding='utf-8'))
    urls=[('manual-'+str(n),urljoin('https://www.tdx.com.cn/products/helpfile/tdxw/',x['Local'])) for n,x in enumerate(findings['official_section_paths'])]
    urls += [('sdk-'+str(n),urljoin('https://www.tdx.com.cn/products/',x['path'])) for n,x in enumerate(findings['official_sdk_download_references'])]
    result=[]
    for name,url in urls:
        item={'name':name,'url':url}
        try:
            request_url=quote(url,safe=':/?%=&')
            file=OUT/(name+Path(url).suffix)
            run=subprocess.run(['curl.exe','--noproxy','*','--connect-timeout','5','--max-time','12','--location','--silent','--show-error','--output',str(file),'--write-out','%{http_code}',request_url],capture_output=True,timeout=15)
            item.update(status=run.stdout.decode('ascii',errors='replace'),request_url=request_url,curl_returncode=run.returncode)
            if run.returncode or run.stdout!=b'200': raise RuntimeError(run.stderr.decode('utf-8',errors='replace') or 'HTTP '+str(item['status']))
            body=file.read_bytes()
            item.update(file=file.name,size=len(body),sha256=hashlib.sha256(body).hexdigest())
            if file.suffix=='.rar':
                listing=subprocess.run([r'C:\Program Files\WinRAR\UnRAR.exe','lb',str(file)],capture_output=True,stdin=subprocess.DEVNULL,timeout=15)
                members=listing.stdout.decode('gb18030',errors='replace').splitlines()
                item['members']=members
                destination=OUT/'sdk-extracted'; destination.mkdir()
                for member in members:
                    target=(destination/member).resolve()
                    if not target.is_relative_to(destination.resolve()): raise ValueError('Unsafe SDK archive path')
                extracted=subprocess.run([r'C:\Program Files\WinRAR\UnRAR.exe','x','-o-',str(file),str(destination)+'\\'],capture_output=True,stdin=subprocess.DEVNULL,timeout=15)
                item.update(extraction_returncode=extracted.returncode,contents_not_executed=True)
        except Exception as exc: item.update(error=str(exc))
        result.append(item)
    headers=[]
    for file in OUT.rglob('*'):
        if file.suffix.lower() in ('.h','.cpp'):
            data=file.read_bytes()
            text=data.decode('gb18030',errors='replace')
            headers.append({'path':file.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(data).hexdigest(),'contract_lines':[line.strip() for line in text.splitlines() if any(word in line for word in ('typedef','RegisterTdxFunc','DataLen','pfOUT','pfIN','pPluginFUNC','PluginTCalcFuncInfo'))]})
    (OUT/'sources.json').write_text(json.dumps({'documents':result,'header_contracts':headers},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'documents':[(x['name'],x.get('status'),x.get('error')) for x in result],'headers':headers},ensure_ascii=True,indent=2))

if __name__=='__main__': main()
