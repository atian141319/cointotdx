"""Bounded live semantics checks; responses kept in data/raw for review."""
import hashlib, json, sqlite3, subprocess, sys
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import bridge as b

root=Path(__file__).resolve().parents[1]
c=b.config(root/'config.smoke.json'); s=b.Store(c['data_dir']); api=b.API(c)
report={'result':'collector-only','terminal_verified':False,'checks':[],'source':'official-binance-spot-public'}
def fingerprint():
    rows=s.db.execute('SELECT exchange,market,symbol,interval,open_ms,payload,final FROM bars ORDER BY symbol,interval,open_ms').fetchall()
    return hashlib.sha256(json.dumps(rows,separators=(',',':')).encode()).hexdigest()
try:
    before=fingerprint()
    with b.Instance(c['data_dir']): b.synchronize(c)
    after=fingerprint()
    report['idempotent_rerun']={'before':before,'after':after,'equal':before==after}
    if before!=after: raise ValueError('re-run data changed; inspect revisions')
    for symbol in ('BTCUSDT','ETHUSDT'):
        for start,end in [('2024-02-28T23:55:00Z','2024-02-29T00:05:00Z'),('2024-02-29T23:55:00Z','2024-03-01T00:05:00Z'),('2024-12-31T23:55:00Z','2025-01-01T00:05:00Z')]:
            rows,raw=api.get('klines',symbol=symbol,interval='1m',startTime=b.ms(start),endTime=b.ms(end)-1,limit=20,timeZone='0')
            expected=list(range(b.ms(start),b.ms(end),60000))
            if [r[0] for r in rows]!=expected: raise ValueError('missing calendar sample')
            report['checks'].append({'symbol':symbol,'case':start,'rows':len(rows),'raw_id':raw,'consecutive':True})
        for start,end in [('2024-02-01T00:00:00Z','2024-03-01T00:00:00Z'),('2024-12-01T00:00:00Z','2025-01-01T00:00:00Z')]:
            daily,daily_raw=api.get('klines',symbol=symbol,interval='1d',startTime=b.ms(start),endTime=b.ms(end)-1,limit=32,timeZone='0')
            monthly,month_raw=api.get('klines',symbol=symbol,interval='1M',startTime=b.ms(start),endTime=b.ms(end)-1,limit=1,timeZone='0')
            expected=list(range(b.ms(start),b.ms(end),86400000))
            if [r[0] for r in daily]!=expected or len(monthly)!=1: raise ValueError('missing month source data')
            with localcontext() as ctx:
                ctx.prec=80
                aggregated=[Decimal(daily[0][1]),max(Decimal(r[2]) for r in daily),min(Decimal(r[3]) for r in daily),Decimal(daily[-1][4]),sum((Decimal(r[5]) for r in daily),Decimal(0)),sum((Decimal(r[7]) for r in daily),Decimal(0))]
                native=[Decimal(monthly[0][i]) for i in (1,2,3,4,5,7)]
                differences=[str(x-y) for x,y in zip(aggregated,native)]
            exact=all(Decimal(x)==0 for x in differences)
            report['checks'].append({'symbol':symbol,'case':'daily-to-natural-month','start':start,'days':len(daily),'daily_raw':daily_raw,'month_raw':month_raw,'OHLCV_quote_differences':differences,'exact':exact})
            if not exact: raise ValueError('native period semantics differ; GPT review required')
finally:
    s.db.close()
    (root/'evidence'/'live-semantics.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
