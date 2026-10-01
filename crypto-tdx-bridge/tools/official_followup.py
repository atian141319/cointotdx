"""Read official manual index pages, follow only relevant documentation links."""
import concurrent.futures
import hashlib
import json
import re
import zipfile
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, build_opener, ProxyHandler

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence'/'r1'/'technical'/'official-followup'
PAGES=[('manual-left','https://www.tdx.com.cn/products/helpfile/tdxw/left.html'),
       ('redbook','https://www.tdx.com.cn/products/user_redbook_style2.html'),
       ('quant-market','https://help.tdx.com.cn/quant/docs/markdown/mindoc-1ctuhthaq5qmg.html')]

def fetch(item):
    name,url=item
    result={'name':name,'url':url}
    try:
        with build_opener(ProxyHandler({})).open(Request(url,headers={'User-Agent':'crypto-tdx-r1-document-audit'}),timeout=15) as response:
            data=response.read(); result.update(status=response.status,final_url=response.url)
        path=OUT/(name+'.source'); path.write_bytes(data)
        result.update(file=path.name,sha256=hashlib.sha256(data).hexdigest(),size=len(data))
        text=data.decode('utf-8',errors='replace')
        if '\ufffd' in text: text=data.decode('gb18030',errors='replace')
        links=[]
        for href,title in re.findall(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',text,re.S|re.I):
            label=unescape(re.sub('<[^>]+>','',title)).strip()
            resolved=urljoin(url,unescape(href))
            if urlparse(resolved).hostname in ('www.tdx.com.cn','help.tdx.com.cn','data.tdx.com.cn'):
                links.append({'url':resolved,'label':label})
        result['links']=links
    except Exception as exc: result.update(error=str(exc),status='UNAVAILABLE')
    return result

def main():
    OUT.mkdir(parents=True,exist_ok=False)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        result=list(pool.map(fetch,PAGES))
    selected=[]
    for item in result:
        for link in item.get('links',[]):
            if re.search('定制|外部|数据管理|数据维护|DLL|插件|历史行情|下载行情|download_history|get_market_data|refresh',link['label']+' '+link['url'],re.I):
                selected.append(link)
    selected=list({item['url']:item for item in selected}.values())[:12]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        extra=list(pool.map(fetch,[(f'linked-{i}',x['url']) for i,x in enumerate(selected)]))
    (OUT/'sources.json').write_text(json.dumps({'index_pages':result,'selected_links':selected,'followed':extra},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'selected_links':selected,'statuses':[(x['name'],x['status']) for x in result+extra]},ensure_ascii=True,indent=2))

if __name__=='__main__': main()
