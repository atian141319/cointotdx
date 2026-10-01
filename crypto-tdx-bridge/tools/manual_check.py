"""Extract official help-index references and list bundled archives without execution."""
import hashlib
import json
import re
import subprocess
import zipfile
from html import unescape
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
TECH=ROOT/'evidence'/'r1'/'technical'

def main():
    source=TECH/'official-followup'/'manual-left.source'
    text=source.read_text(encoding='utf-8')
    match=re.search(r'CHM_DATA=(\[.*?\]);',text,re.S)
    # Do not execute the site's JavaScript. Preserve JS-only unknown escapes as
    # literal backslashes for textual inspection rather than evaluating code.
    data=[item.replace(chr(92)+'"','"').replace(chr(92)*2,chr(92))
          for item in re.findall(r'"((?:\\.|[^"\\])*)"',match.group(1))]
    matches=[]
    for i in range(1,len(data),2):
        title=data[i-1]; body=data[i]
        if any(word in title for word in ('定制品种','数据维护','数据管理','DLL')) or ('外部品种' in body):
            matches.append({'title_path':title,'body':body})
    paths=[]
    for block in re.findall(r'<OBJECT\b.*?</OBJECT>',text,re.S|re.I):
        values=dict(re.findall(r'<param\s+name="([^"]+)"\s+value="([^"]*)"',block,re.I))
        if any(word in values.get('Name','') for word in ('定制品种','数据维护','数据管理','DLL')):
            paths.append(values)
    redbook=(TECH/'official-followup'/'redbook.source').read_bytes().decode('gb18030',errors='replace')
    downloads=[]
    for href,body in re.findall(r'<a\b[^>]*href=([^\s>]+)[^>]*>(.*?)</a>',redbook,re.S|re.I):
        title=unescape(re.sub('<[^>]+>','',body)).strip()
        if any(word in title for word in ('DLL','接口','SDK')):
            downloads.append({'path':href.strip('"\''),'title':title})
    archives=[]
    for path in [Path(r'D:\Programs\tdx\datatool\wintool.rar'),Path(r'D:\Programs\tdx\datatool\v3\down\downit.zip'),Path(r'D:\Programs\tdx\datatool\v4\down\downit.zip')]:
        entry={'source':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'contents_not_executed':True}
        if path.suffix=='.zip':
            with zipfile.ZipFile(path) as package: entry['members']=package.namelist()
        else:
            run=subprocess.run([r'C:\Program Files\WinRAR\UnRAR.exe','lb',str(path)],capture_output=True)
            entry.update(listing_returncode=run.returncode,members=run.stdout.decode('gb18030',errors='replace').splitlines())
        archives.append(entry)
    result={'manual_index_source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'manual_sections':matches,'official_section_paths':paths,'official_sdk_download_references':downloads,'local_archive_listings':archives}
    (TECH/'manual-findings.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True,indent=2))

if __name__=='__main__': main()
