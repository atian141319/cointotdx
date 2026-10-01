"""Binance spot public collector. Python 3.11+, standard library only."""
from __future__ import annotations
import argparse, csv, hashlib, json, logging, math, os, re, sqlite3, sys, time, uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, Inexact, localcontext
from pathlib import Path
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from rate_control import CooldownBlocked, RateGate

UTC = timezone.utc
INTERVALS = ('1m','5m','15m','30m','1h','1d','1w','1M')
HOSTS = ('https://data-api.binance.vision','https://api.binance.com')
FIELDS = ('open','high','low','close','base_volume','quote_volume')
FILE_PERIODS = {'1m':'minute-1','5m':'minute-5','15m':'minute-15','30m':'minute-30','1h':'hour-1','1d':'day-1','1w':'week-1','1M':'month-1'}

def ms(value):
    d = datetime.fromisoformat(value.replace('Z','+00:00'))
    if d.tzinfo is None: raise ValueError('时间必须包含 UTC 偏移')
    return int(d.timestamp()*1000)

def dt(value): return datetime.fromtimestamp(value/1000, UTC)

def floor(value, interval):
    d = dt(value)
    if interval == '1M': return int(d.replace(day=1,hour=0,minute=0,second=0,microsecond=0).timestamp()*1000)
    if interval == '1w':
        d = d.replace(hour=0,minute=0,second=0,microsecond=0)-timedelta(days=d.weekday())
        return int(d.timestamp()*1000)
    size = {'1m':60000,'5m':300000,'15m':900000,'30m':1800000,'1h':3600000,'1d':86400000}[interval]
    return value//size*size

def next_time(value, interval):
    if interval == '1M':
        d = dt(value)
        return int(d.replace(year=d.year+(d.month==12),month=d.month%12+1,day=1).timestamp()*1000)
    if interval == '1w': return value+7*86400000
    return value+{'1m':60000,'5m':300000,'15m':900000,'30m':1800000,'1h':3600000,'1d':86400000}[interval]

def config(path):
    path = Path(path).resolve()
    c = json.loads(path.read_text(encoding='utf-8-sig'))
    if c.get('base_url') not in HOSTS: raise ValueError('仅允许币安官方公开行情主机')
    pairs = c['pairs']
    if not pairs or len({p['symbol'] for p in pairs}) != len(pairs): raise ValueError('交易对为空或重复')
    for p in pairs:
        if not re.fullmatch('[A-Z0-9]{5,30}',p['symbol']): raise ValueError('无效交易对')
        if type(p.get('enabled',True)) is not bool: raise ValueError('enabled 必须是布尔值')
        ms(p.get('history_start',c['history_start']))
    if len(c['intervals'])!=len(INTERVALS) or set(c['intervals']) != set(INTERVALS): raise ValueError('必须配置全部八个目标周期且不得重复')
    for key in ('sync_seconds','timeout_seconds','request_spacing_seconds'):
        if not isinstance(c[key],(int,float)) or isinstance(c[key],bool) or not math.isfinite(c[key]) or c[key]<=0: raise ValueError(key)
    if type(c['retries']) is not int or not 0<=c['retries']<=10: raise ValueError('retries 范围 0..10')
    if type(c['page_limit']) is not int or not 1<=c['page_limit']<=1000: raise ValueError('page_limit 范围 1..1000')
    if c.get('history_end'): ms(c['history_end'])
    c.setdefault('empty_backoff_seconds',60)
    c.setdefault('empty_backoff_max_seconds',3600)
    for key in ('empty_backoff_seconds','empty_backoff_max_seconds'):
        if not isinstance(c[key],(int,float)) or isinstance(c[key],bool) or not math.isfinite(c[key]) or c[key]<=0: raise ValueError(key)
    if c['empty_backoff_max_seconds']<c['empty_backoff_seconds']: raise ValueError('空区间退避上限小于初始值')
    for key in ('data_dir','output_dir'):
        c[key] = str((path.parent/c[key]).resolve())
    if Path(c['data_dir']) == Path(c['output_dir']): raise ValueError('数据目录与输出目录必须分离')
    forbidden = Path(r'D:\Programs\tdx').resolve()
    if any(Path(c[key])==forbidden or forbidden in Path(c[key]).parents for key in ('data_dir','output_dir')):
        raise ValueError('P0 尚未验证，不允许将采集或审计输出写入已知终端安装目录')
    c['_path'] = str(path)
    return c

class Instance:
    def __init__(self, directory): self.path = Path(directory)/'instance.lock'
    def __enter__(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.f = self.path.open('a+b')
        try:
            if self.path.stat().st_size==0: self.f.write(b'0'); self.f.flush()
            self.f.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.f.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.f.close(); raise RuntimeError('已有实例运行')
        return self
    def __exit__(self,*args):
        if os.name=='nt':
            import msvcrt
            self.f.seek(0); msvcrt.locking(self.f.fileno(),msvcrt.LK_UNLCK,1)
        self.f.close()

class Halt(RuntimeError): pass
class Stopped(RuntimeError): pass

def cancellable_wait(seconds,stop):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        if stop.exists(): raise Stopped('已收到停止请求')
        time.sleep(min(1,max(0,deadline-time.monotonic())))

class API:
    def __init__(self,c,rate_path=None,now=None):
        self.c=c; self.last=0; self.halted=False
        self.raw=Path(c['data_dir'])/'raw'; self.raw.mkdir(parents=True,exist_ok=True)
        self.opener=build_opener(ProxyHandler({})) # direct only, no proxy changes
        self.stop=Path(c['data_dir'])/'STOP'
        self.gate=RateGate(rate_path,now)
    def get(self,endpoint,**params):
        if self.halted: raise Halt('本轮已停止请求')
        if endpoint not in ('ping','time','exchangeInfo','klines'): raise ValueError('禁止非公开行情端点')
        url=self.c['base_url']+'/api/v3/'+endpoint+('?' + urlencode(params) if params else '')
        for attempt in range(self.c['retries']+1):
            if self.stop.exists(): raise Stopped('已收到停止请求')
            cancellable_wait(max(0,self.c['request_spacing_seconds']-(time.monotonic()-self.last)),self.stop)
            self.last=time.monotonic()
            status=None; headers={}; body=b''; error=None
            ident=uuid.uuid4().hex
            try:
                with self.gate.request() as rate_db:
                    try:
                        with self.opener.open(Request(url,headers={'User-Agent':'crypto-tdx-bridge/0.1'}),timeout=self.c['timeout_seconds']) as r:
                            status=r.status; headers=dict(r.headers); body=r.read()
                    except HTTPError as e:
                        try: status=e.code; headers=dict(e.headers); body=e.read(); error=str(e)
                        finally: e.close()
                    except (URLError,TimeoutError,OSError) as e: error=str(e)
                    cooling=self.gate.record(rate_db,status,headers,ident,url,body)
            except CooldownBlocked as exc:
                self.halted=True; raise Halt(str(exc)) from exc
            (self.raw/(ident+'.body')).write_bytes(body)
            evidence={'url':url,'status':status,'headers':headers,'error':error,'observed_utc':datetime.now(UTC).isoformat(),'body_sha256':hashlib.sha256(body).hexdigest()}
            (self.raw/(ident+'.json')).write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
            if status==200:
                return json.loads(body), ident
            logging.error('API %s status=%s error=%s raw=%s',endpoint,status,error,ident)
            if status in (403,418,451):
                self.halted=True; raise Halt(f'HTTP {status}: 本轮停止；未改变代理或部署中转')
            if cooling and cooling['manual_review']:
                self.halted=True; raise Halt(f'HTTP {status} Retry-After 无法可靠解析，持久阻断等待复核: {cooling}')
            if status is not None and status not in (429,500,502,503,504): raise RuntimeError(f'HTTP {status}: {body[:500]!r}')
            if attempt==self.c['retries']:
                if status==429:
                    self.halted=True; raise Halt('HTTP 429 重试耗尽；停止运行，避免下轮提前违反 Retry-After')
                raise RuntimeError(f'请求重试耗尽: {endpoint} status={status} {error}')
            wait=min(60,2**attempt)
            if cooling:
                wait=max(wait,cooling['deadline']-self.gate.now())
            logging.warning('等待 %.2f 秒后重试',wait)
            cancellable_wait(max(0,wait),self.stop)
        raise AssertionError()

class Store:
    def __init__(self,directory):
        Path(directory).mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(Path(directory)/'market.sqlite3')
        self.db.execute('PRAGMA journal_mode=WAL'); self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS bars(exchange TEXT,market TEXT,symbol TEXT,interval TEXT,open_ms INTEGER,close_ms INTEGER,payload TEXT,final INTEGER,raw_id TEXT, PRIMARY KEY(exchange,market,symbol,interval,open_ms));
        CREATE TABLE IF NOT EXISTS revisions(id INTEGER PRIMARY KEY,symbol TEXT,interval TEXT,open_ms INTEGER,old_payload TEXT,new_payload TEXT,old_raw TEXT,new_raw TEXT,observed_utc TEXT);
        CREATE TABLE IF NOT EXISTS progress(symbol TEXT,interval TEXT,next_ms INTEGER, PRIMARY KEY(symbol,interval));
        CREATE TABLE IF NOT EXISTS metadata(symbol TEXT PRIMARY KEY,payload TEXT,raw_id TEXT);
        CREATE TABLE IF NOT EXISTS empty_ranges(
            exchange TEXT,market TEXT,symbol TEXT,interval TEXT,start_ms INTEGER,end_ms INTEGER,
            observed_ms INTEGER,server_ms INTEGER,raw_id TEXT,attempts INTEGER,next_check_ms INTEGER,
            state TEXT, strategy TEXT, PRIMARY KEY(exchange,market,symbol,interval,start_ms,end_ms));
        CREATE TABLE IF NOT EXISTS empty_events(
            id INTEGER PRIMARY KEY,symbol TEXT,interval TEXT,start_ms INTEGER,end_ms INTEGER,
            observed_ms INTEGER,server_ms INTEGER,raw_id TEXT,attempts INTEGER,next_check_ms INTEGER,
            state TEXT,strategy TEXT);
        ''')
    def ingest(self,symbol,interval,rows,server_ms,raw_id):
        previous=-1
        with self.db:
            for r in rows:
                if len(r)!=12 or type(r[0]) is not int or r[0]<=previous or floor(r[0],interval)!=r[0] or r[6]!=next_time(r[0],interval)-1: raise ValueError('K线时间/结构不合法')
                previous=r[0]
                values=[Decimal(r[i]) for i in (1,2,3,4,5,7,9,10)]
                if any(not v.is_finite() or v<0 for v in values): raise ValueError('非有限或负数行情')
                o,h,l,c=values[:4]
                if not l<=min(o,c)<=max(o,c)<=h: raise ValueError('OHLC 不合法')
                if type(r[8]) is not int or r[8]<0: raise ValueError('成交笔数不合法')
                payload=json.dumps(r,separators=(',',':')); final=int(r[6]<server_ms)
                old=self.db.execute("SELECT payload,raw_id,final FROM bars WHERE exchange='binance' AND market='spot' AND symbol=? AND interval=? AND open_ms=?",(symbol,interval,r[0])).fetchone()
                if old and old[2] and not final: raise ValueError('服务端时间倒退，禁止最终状态回退')
                if old and old[0]!=payload:
                    self.db.execute('INSERT INTO revisions(symbol,interval,open_ms,old_payload,new_payload,old_raw,new_raw,observed_utc) VALUES(?,?,?,?,?,?,?,?)',(symbol,interval,r[0],old[0],payload,old[1],raw_id,datetime.now(UTC).isoformat()))
                self.db.execute('INSERT OR REPLACE INTO bars VALUES(?,?,?,?,?,?,?,?,?)',('binance','spot',symbol,interval,r[0],r[6],payload,final,raw_id))
            if rows:
                self.db.execute('INSERT OR REPLACE INTO progress VALUES(?,?,?)',(symbol,interval,next_time(rows[-1][0],interval)))
                # A newly returned row makes old "entire range empty" evidence
                # stale. Remaining holes are still discovered from actual bars.
                self.db.executemany("UPDATE empty_ranges SET state='data_observed',next_check_ms=0 WHERE exchange='binance' AND market='spot' AND symbol=? AND interval=? AND state IN ('pending_verification','unclosed_absent') AND start_ms<=? AND end_ms>?", ((symbol,interval,r[0],r[0]) for r in rows))

    def note_empty(self,symbol,interval,start,end,server_ms,raw_id,c,now_ms=None):
        observed=now_ms if now_ms is not None else int(time.time()*1000)
        old=self.db.execute('SELECT attempts FROM empty_ranges WHERE symbol=? AND interval=? AND start_ms=? AND end_ms=?',(symbol,interval,start,end)).fetchone()
        attempts=(old[0] if old else 0)+1
        delay=min(c.get('empty_backoff_max_seconds',3600),c.get('empty_backoff_seconds',60)*2**min(attempts-1,30))
        next_check=observed+math.ceil(delay*1000)
        state='unclosed_absent' if start>=floor(server_ms,interval) else 'pending_verification'
        strategy=json.dumps({'policy':'bounded-exponential-recheck','delay_seconds':delay,'max_seconds':c.get('empty_backoff_max_seconds',3600),'force_supported':True,'not_proof_of_unlisted':True})
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO empty_ranges VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',('binance','spot',symbol,interval,start,end,observed,server_ms,raw_id,attempts,next_check,state,strategy))
            self.db.execute('INSERT INTO empty_events(symbol,interval,start_ms,end_ms,observed_ms,server_ms,raw_id,attempts,next_check_ms,state,strategy) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(symbol,interval,start,end,observed,server_ms,raw_id,attempts,next_check,state,strategy))

    def recheck_windows(self,symbol,interval,start,end,force=False,now_ms=None):
        if force: return [(start,end)]
        now=now_ms if now_ms is not None else int(time.time()*1000)
        ranges=self.db.execute("SELECT start_ms,end_ms FROM empty_ranges WHERE symbol=? AND interval=? AND state IN ('pending_verification','unclosed_absent') AND next_check_ms>? AND start_ms<? AND end_ms>? ORDER BY start_ms",(symbol,interval,now,end,start)).fetchall()
        windows=[]; cursor=start
        for lo,hi in ranges:
            hi=next_time(floor(hi-1,interval),interval)
            if lo>cursor: windows.append((cursor,min(lo,end)))
            cursor=max(cursor,min(hi,end))
        if cursor<end: windows.append((cursor,end))
        return windows
    def gaps(self,symbol,interval,start,end):
        cursor=floor(start,interval); result=[]
        rows=self.db.execute("SELECT open_ms FROM bars WHERE symbol=? AND interval=? AND final=1 AND open_ms>=? AND open_ms<? ORDER BY open_ms",(symbol,interval,cursor,end))
        for (value,) in rows:
            if value>cursor: result.append((cursor,value))
            cursor=next_time(value,interval)
        if cursor<end: result.append((cursor,end))
        return result

def validate_metadata(api,store,c):
    active=[p['symbol'] for p in c['pairs'] if p.get('enabled',True)]
    if not active: return
    data,raw=api.get('exchangeInfo',symbols=json.dumps(active,separators=(',',':')))
    found={x['symbol']:x for x in data['symbols']}
    for symbol in active:
        m=found.get(symbol)
        if not m or m['status']!='TRADING' or not m.get('isSpotTradingAllowed',False): raise ValueError(f'{symbol} 不是可交易现货品种')
        with store.db: store.db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?,?)',(symbol,json.dumps(m),raw))

def download(api,store,c,symbol,interval,start,end,force_recheck=False):
    for lo,hi in store.recheck_windows(symbol,interval,floor(start,interval),end,force_recheck):
        download_window(api,store,c,symbol,interval,lo,hi)

def download_window(api,store,c,symbol,interval,start,end):
    cursor=floor(start,interval)
    while cursor<end:
        # Clock BEFORE retrieval: a response fetched just before close must not be
        # finalized merely because the following clock request crosses the boundary.
        clock,_=api.get('time')
        rows,raw=api.get('klines',symbol=symbol,interval=interval,startTime=cursor,endTime=end-1,limit=c['page_limit'],timeZone='0')
        if not rows:
            store.note_empty(symbol,interval,cursor,end,clock['serverTime'],raw,c)
            logging.warning('待核实空区间 %s %s %s..%s raw=%s；保留缺口并有界退避重查',symbol,interval,cursor,end,raw)
            return
        if any(r[0]<cursor or r[0]>=end for r in rows): raise ValueError('API 返回越界数据')
        store.ingest(symbol,interval,rows,clock['serverTime'],raw)
        new=next_time(rows[-1][0],interval)
        if new<=cursor: raise ValueError('分页未前进')
        cursor=new

def synchronize(c,end_override=None,force_recheck=False):
    store=Store(c['data_dir']); api=API(c)
    try:
        validate_metadata(api,store,c)
        clock,_=api.get('time'); end=clock['serverTime']
        requested_end=end_override or c.get('history_end')
        if requested_end: end=min(end,ms(requested_end))
        for p in c['pairs']:
            if not p.get('enabled',True): continue
            start=ms(p.get('history_start',c['history_start'])); symbol=p['symbol']
            if start>=end: raise ValueError('历史起点必须早于结束时间')
            for interval in c['intervals']:
                closed_end=floor(end,interval)
                for lo,hi in store.gaps(symbol,interval,start,closed_end): download(api,store,c,symbol,interval,lo,hi,force_recheck)
                # Re-fetch overlap for current/final transition and recent revisions.
                recent=store.db.execute('SELECT open_ms FROM bars WHERE symbol=? AND interval=? ORDER BY open_ms DESC LIMIT 3',(symbol,interval)).fetchall()
                overlap=min([r[0] for r in recent]+[closed_end])
                download(api,store,c,symbol,interval,max(floor(start,interval),overlap),end,force_recheck)
    finally: store.db.close()

def aggregate(rows,interval,server_ms):
    groups={}
    for r in rows: groups.setdefault(floor(r[0],interval),[]).append(r)
    result=[]
    with localcontext() as ctx:
        ctx.prec=80
        ctx.traps[Inexact]=True
        for start,items in sorted(groups.items()):
            items=sorted(items,key=lambda r:r[0]); finish=next_time(start,interval)
            complete=(items[0][0]==start and items[-1][0]+60000==finish and len(items)==(finish-start)//60000 and all(b[0]-a[0]==60000 for a,b in zip(items,items[1:])) and finish<=server_ms)
            result.append({'open_ms':start,'complete':complete,'open':items[0][1],'high':str(max(Decimal(r[2]) for r in items)),'low':str(min(Decimal(r[3]) for r in items)),'close':items[-1][4],'base_volume':str(sum((Decimal(r[5]) for r in items),Decimal(0))),'quote_volume':str(sum((Decimal(r[7]) for r in items),Decimal(0)))})
    return result

def publish(c):
    """Exact audit export, explicitly not a verified TDX import format."""
    store=Store(c['data_dir']); out=Path(c['output_dir']); out.mkdir(parents=True,exist_ok=True)
    batch=uuid.uuid4().hex; stage=out/('batch-'+batch); stage.mkdir()
    manifest={'batch':batch,'format':'exact-audit-csv-v1','tdx_verified':False,'timezone':'UTC','time_label':'open','price_unit':'quote asset per base asset','volume_unit':'base asset','amount_unit':'quote asset','export_scope':{'symbols':[p['symbol'] for p in c['pairs']],'intervals':c['intervals']},'files':[]}
    try:
        store.db.execute('BEGIN')
        for p in c['pairs']:
            for interval in c['intervals']:
                name=p['symbol']+'-'+FILE_PERIODS[interval]+'.csv'; file=stage/name
                with file.open('w',encoding='utf-8',newline='') as f:
                    w=csv.writer(f); w.writerow(('symbol','interval','open_utc','close_utc',*FIELDS,'trades','source','raw_id'))
                    for payload,raw in store.db.execute('SELECT payload,raw_id FROM bars WHERE symbol=? AND interval=? AND final=1 ORDER BY open_ms',(p['symbol'],interval)):
                        r=json.loads(payload); w.writerow((p['symbol'],interval,dt(r[0]).isoformat(),dt(r[6]).isoformat(),r[1],r[2],r[3],r[4],r[5],r[7],r[8],'binance-native',raw))
                    f.flush(); os.fsync(f.fileno())
                # independent CSV read and exact numeric parse
                with file.open(encoding='utf-8',newline='') as f:
                    count=0; last=None
                    for row in csv.DictReader(f):
                        for key in FIELDS:
                            if not Decimal(row[key]).is_finite(): raise ValueError('输出非有限值')
                        if last and row['open_utc']<=last: raise ValueError('输出未排序')
                        last=row['open_utc']; count+=1
                bounds=store.db.execute('SELECT min(open_ms),max(open_ms) FROM bars WHERE symbol=? AND interval=? AND final=1',(p['symbol'],interval)).fetchone()
                gaps=store.gaps(p['symbol'],interval,bounds[0],next_time(bounds[1],interval)) if bounds[0] is not None else []
                manifest['files'].append({'name':name,'symbol':p['symbol'],'interval':interval,'rows':count,'sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'first_open_ms':bounds[0],'last_open_ms':bounds[1],'internal_gaps':gaps,'complete_between_bounds':bool(count) and not gaps})
        store.db.rollback()
        m=stage/'manifest.json'; m.write_text(json.dumps(manifest,indent=2),encoding='utf-8')
        with m.open('r+b') as f: os.fsync(f.fileno())
        pointer=out/('CURRENT-'+batch+'.tmp')
        with pointer.open('w',encoding='utf-8') as f:
            json.dump({'batch':stage.name,'manifest_sha256':hashlib.sha256(m.read_bytes()).hexdigest()},f); f.flush(); os.fsync(f.fileno())
        os.replace(pointer,out/'CURRENT.json')
        print(json.dumps(manifest,ensure_ascii=False))
    finally: store.db.close()

def status(c):
    s=Store(c['data_dir']); result={'tdx_minutes':'BLOCKED','series':[]}
    try:
        result['rate_limit_state']=RateGate().inspect()
        end=ms(c['history_end']) if c.get('history_end') else int(time.time()*1000)
        result['gap_end_basis']='configured-history-end' if c.get('history_end') else 'local-clock-estimate'
        for p in c['pairs']:
            for interval in c['intervals']:
                counts=s.db.execute('SELECT final,count(*),min(open_ms),max(open_ms) FROM bars WHERE symbol=? AND interval=? GROUP BY final',(p['symbol'],interval)).fetchall()
                gaps=s.gaps(p['symbol'],interval,ms(p.get('history_start',c['history_start'])),floor(end,interval))
                result['series'].append({'symbol':p['symbol'],'enabled':p.get('enabled',True),'interval':interval,'counts':counts,'gaps':gaps})
        result['revisions']=s.db.execute('SELECT count(*) FROM revisions').fetchone()[0]
        result['empty_observations']=[dict(zip(('symbol','interval','start_ms','end_ms','observed_ms','server_ms','raw_id','attempts','next_check_ms','state','strategy'),r)) for r in s.db.execute('SELECT symbol,interval,start_ms,end_ms,observed_ms,server_ms,raw_id,attempts,next_check_ms,state,strategy FROM empty_ranges ORDER BY symbol,interval,start_ms')]
        result['gap_interpretation']='gaps are missing stored finalized bars; pending empty observations are not confirmed exchange omissions; current periods excluded'
        print(json.dumps(result,ensure_ascii=False,indent=2))
    finally: s.db.close()

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('command',choices=['check','sync','run','status','gaps','export','stop','tdx-export']); parser.add_argument('--config',default='config.json'); parser.add_argument('--end'); parser.add_argument('--force-recheck',action='store_true',help='复查尚未到期的空区间；不能绕过HTTP限流'); args=parser.parse_args()
    c=config(args.config); Path(c['data_dir']).mkdir(parents=True,exist_ok=True)
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s',handlers=[logging.FileHandler(Path(c['data_dir'])/'bridge.log',encoding='utf-8'),logging.StreamHandler()])
    stop=Path(c['data_dir'])/'STOP'
    if args.command=='stop': stop.write_text('requested',encoding='utf-8'); return
    if args.command in ('status','gaps'):
        status(c); return
    with Instance(c['data_dir']):
        if args.command=='tdx-export': raise Halt('P0 未验证外部分钟接入，禁止生成或发布通达信格式')
        if args.command in ('status','gaps'): status(c)
        elif args.command=='export': publish(c)
        elif args.command=='check':
            api=API(c); s=Store(c['data_dir'])
            try:
                ping,_=api.get('ping'); clock,_=api.get('time'); validate_metadata(api,s,c)
                print(json.dumps({'ping':ping,'server_time':clock,'metadata':'validated','direct':True,'python':sys.version,'platform':sys.platform},indent=2))
            finally: s.db.close()
        elif args.command=='sync':
            stop.unlink(missing_ok=True); synchronize(c,args.end,args.force_recheck)
        elif args.command=='run':
            stop.unlink(missing_ok=True)
            while not stop.exists():
                try:
                    updated=config(args.config)
                    if updated['data_dir']!=c['data_dir']: raise Halt('运行期间禁止切换数据目录；请停止后重启')
                    c=updated; synchronize(c); publish(c)
                except Stopped: break
                except Halt: raise
                except Exception: logging.exception('同步失败；下轮补缺')
                deadline=time.monotonic()+c['sync_seconds']
                while time.monotonic()<deadline and not stop.exists(): time.sleep(min(1,max(0,deadline-time.monotonic())))

if __name__=='__main__':
    try: main()
    except KeyboardInterrupt: print('已停止；已提交页保留，锁由操作系统释放',file=sys.stderr)
    except Exception as e: logging.exception('失败: %s',e); sys.exit(1)
