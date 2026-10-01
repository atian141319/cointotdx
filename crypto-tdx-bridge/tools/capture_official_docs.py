"""Snapshot known official documentation only; no account/API or client writes."""
import concurrent.futures
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, build_opener, ProxyHandler

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence'/'r1'/'technical'/'official'
URLS={
    'binance-rest':'https://raw.githubusercontent.com/binance/binance-spot-api-docs/master/rest-api.md',
    'tdx-release-764':'https://www.tdx.com.cn/article/soft_7_64.html',
    'tdx-functions':'https://help.tdx.com.cn/gspt/docs/markdown/redword/functionlist.html',
    'tdx-http-data':'https://help.tdx.com.cn/quant/docs/markdown/mindoc-1hdhbmi50d038.html',
    'tdx-send-file':'https://help.tdx.com.cn/quant/docs/markdown/ctx.stock.md/mindoc-1h10u17ue9464.html',
    'tdx-aidata':'https://help.tdx.com.cn/quant/docs/markdown/mindoc-1hjbgqpdhv114.html',
    'tdx-help-index':'https://www.tdx.com.cn/products/helpfile/tdxw/index.html',
    'tdx-book':'https://help.tdx.com.cn/book.asp'
}

def fetch(item):
    name,url=item
    result={'name':name,'url':url,'observed_utc':datetime.now(timezone.utc).isoformat()}
    try:
        with build_opener(ProxyHandler({})).open(Request(url,headers={'User-Agent':'crypto-tdx-r1-document-audit'}),timeout=15) as response:
            data=response.read(); result.update(status=response.status,final_url=response.url,headers=dict(response.headers))
        path=OUT/(name+'.source'); path.write_bytes(data)
        result.update(file=path.name,size=len(data),sha256=hashlib.sha256(data).hexdigest())
    except Exception as exc:
        result.update(error_type=type(exc).__name__,error=str(exc),status='UNAVAILABLE')
    return result

def main():
    OUT.mkdir(parents=True,exist_ok=False)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        result=list(pool.map(fetch,URLS.items()))
    (OUT/'sources.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True,indent=2))

if __name__=='__main__': main()
