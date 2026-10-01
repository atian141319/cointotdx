"""Resume the official formula SDK into a NEW evidence directory; never execute SDK code."""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from urllib.parse import quote

ROOT=Path(__file__).resolve().parents[1]
TECH=ROOT/'evidence'/'r1'/'technical'
OUT=TECH/'official-sdk-complete'

def main():
    OUT.mkdir(parents=True,exist_ok=False)
    original=TECH/'official-sdk-bounded'/'sdk-1.rar'
    target=OUT/'formula-sdk.rar'
    shutil.copy2(original,target)
    url='https://www.tdx.com.cn/products/userdoc/通达信DLL函数编程规范.rar'
    run=subprocess.run(['curl.exe','--noproxy','*','--connect-timeout','5','--max-time','180','--continue-at','-','--silent','--show-error','--output',str(target),'--write-out','%{http_code}',quote(url,safe=':/')],capture_output=True,timeout=185)
    report={'url':url,'resumed_from_bytes':original.stat().st_size,'original_partial_sha256':hashlib.sha256(original.read_bytes()).hexdigest(),
            'curl_returncode':run.returncode,'http_status':run.stdout.decode('ascii',errors='replace'),'error':run.stderr.decode('utf-8',errors='replace'),
            'result_bytes':target.stat().st_size,'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'sdk_code_not_executed':True}
    if run.returncode==0:
        check=subprocess.run([r'C:\Program Files\WinRAR\UnRAR.exe','t',str(target)],capture_output=True,stdin=subprocess.DEVNULL,timeout=20)
        report['archive_test_returncode']=check.returncode
        if check.returncode==0:
            listing=subprocess.run([r'C:\Program Files\WinRAR\UnRAR.exe','lb',str(target)],capture_output=True,stdin=subprocess.DEVNULL,timeout=15)
            members=listing.stdout.decode('gb18030',errors='replace').splitlines()
            destination=OUT/'extracted'; destination.mkdir()
            for member in members:
                if not (destination/member).resolve().is_relative_to(destination.resolve()): raise ValueError('Unsafe archive member')
            extract=subprocess.run([r'C:\Program Files\WinRAR\UnRAR.exe','x','-o-',str(target),str(destination)+'\\'],capture_output=True,stdin=subprocess.DEVNULL,timeout=20)
            report.update(members=members,extraction_returncode=extract.returncode)
            headers=[]
            for file in destination.rglob('*'):
                if file.suffix.lower() in ('.h','.cpp'):
                    data=file.read_bytes(); text=data.decode('gb18030',errors='replace')
                    headers.append({'path':file.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(data).hexdigest(),'contract_lines':[line.strip() for line in text.splitlines() if any(x in line for x in ('typedef','RegisterTdxFunc','DataLen','pfOUT','pfIN','pPluginFUNC','PluginTCalcFuncInfo'))]})
            report['header_contracts']=headers
    (OUT/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True,indent=2))

if __name__=='__main__': main()
