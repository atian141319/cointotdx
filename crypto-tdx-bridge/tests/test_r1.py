import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bridge as b
from rate_control import RateGate, CooldownBlocked


class Reply:
    status = 200
    headers = {}
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self): return b'{}'


class RateTests(unittest.TestCase):
    def config(self, directory):
        return {'data_dir':str(directory / 'data'), 'base_url':b.HOSTS[0],
                'retries':0, 'timeout_seconds':1, 'request_spacing_seconds':0.001}

    def test_final_retry_persists_and_blocks_other_process_commands_and_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = root / 'CryptoTdxBridge' / 'rate-control.sqlite3'
            c = self.config(root)
            api = b.API(c, rate_path=ledger)
            error = HTTPError('u', 429, 'limited', {'Retry-After':'600'}, io.BytesIO(b'limited'))
            with patch.object(api.opener, 'open', side_effect=error):
                with self.assertRaises(b.Halt): api.get('ping')
            con = sqlite3.connect(ledger)
            self.assertGreater(con.execute('SELECT deadline FROM cooldown').fetchone()[0], time.time()+590)
            self.assertEqual(con.execute('SELECT count(*) FROM rate_events').fetchone()[0], 1)
            con.close()
            cfg = json.loads((Path(b.__file__).parent / 'config.smoke.json').read_text())
            cfg.update(base_url=b.HOSTS[1], data_dir=str(root/'different-data'), output_dir=str(root/'out'))
            path = root / 'config.json'; path.write_text(json.dumps(cfg))
            # Child uses real CLI implementation, a different data directory and
            # official host. Any opener invocation is an explicit test failure.
            child_code = "import bridge,sys; from unittest.mock import patch; sys.argv=['bridge.py',sys.argv[1],'--config',sys.argv[2]]; blocked=patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('NETWORK_CALLED')); blocked.start(); bridge.main()"
            for command in ('check','sync','run'):
                child = subprocess.run([sys.executable,'-c',child_code,command,str(path)], cwd=Path(b.__file__).parent, env={**os.environ,'LOCALAPPDATA':str(root),'PYTHONUTF8':'1'}, capture_output=True, text=True, encoding='utf-8', timeout=10)
                self.assertNotEqual(child.returncode,0)
                self.assertIn('持久限流阻断',child.stderr)
                self.assertNotIn('AssertionError: NETWORK_CALLED',child.stderr)

    def test_418_deadline_expiry_recovers_and_date_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); ledger=root/'rate.sqlite3'; clock=[100.0]
            api=b.API(self.config(root),rate_path=ledger,now=lambda:clock[0])
            error=HTTPError('u',418,'banned',{'Retry-After':'20'},io.BytesIO(b'ban'))
            with patch.object(api.opener,'open',side_effect=error):
                with self.assertRaises(b.Halt): api.get('ping')
            new=b.API(self.config(root),rate_path=ledger,now=lambda:clock[0])
            with patch.object(new.opener,'open',return_value=Reply()) as opened:
                with self.assertRaises(b.Halt): new.get('time')
                opened.assert_not_called()
            clock[0]=120.01
            resumed=b.API(self.config(root),rate_path=ledger,now=lambda:clock[0])
            with patch.object(resumed.opener,'open',return_value=Reply()) as opened:
                self.assertEqual(resumed.get('ping')[0],{})
                opened.assert_called_once()
            gate=RateGate(root/'date.sqlite3',now=lambda:100)
            with gate.request() as con:
                state=gate.record(con,429,{'Retry-After':'Thu, 01 Jan 1970 00:03:00 GMT'},'r','u',b'')
            self.assertEqual(state['deadline'],180)

    def test_invalid_missing_retry_after_remains_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            for index, value in enumerate((None, 'NaN', '-1', 'tomorrow', '1e309')):
                gate=RateGate(Path(tmp)/(str(index)+'.sqlite3'),now=lambda:100)
                headers={} if value is None else {'Retry-After':value}
                with gate.request() as con: result=gate.record(con,429,headers,'raw-ref','https://data-api.binance.vision/api/v3/ping',b'blocked')
                self.assertTrue(result['manual_review'])
                restarted=RateGate(gate.path,now=lambda:1000000)
                with self.assertRaises(CooldownBlocked):
                    with restarted.request(): pass
                con=sqlite3.connect(gate.path)
                reason=con.execute('SELECT reason FROM cooldown').fetchone()[0]
                self.assertIn('raw-ref',reason); self.assertIn('parse_error',reason)
                con.close()

    def test_last_response_deadline_overrides_earlier_and_418_cross_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); ledger=root/'rate.sqlite3'; clock=[time.time()]
            c=self.config(root); c['retries']=1
            api=b.API(c,rate_path=ledger,now=lambda:clock[0])
            errors=[HTTPError('u',429,'first',{'Retry-After':'7'},io.BytesIO(b'first')),
                    HTTPError('u',429,'last',{'Retry-After':'600'},io.BytesIO(b'last'))]
            def advance(seconds,stop): clock[0]+=seconds
            with patch.object(api.opener,'open',side_effect=errors),patch('bridge.cancellable_wait',side_effect=advance):
                with self.assertRaises(b.Halt): api.get('ping')
            con=sqlite3.connect(ledger)
            self.assertGreater(con.execute('SELECT deadline FROM cooldown').fetchone()[0],time.time()+600)
            self.assertEqual(con.execute('SELECT count(*) FROM rate_events').fetchone()[0],2)
            con.close()
            gate=RateGate(ledger)
            con=gate.connect()
            con.execute('BEGIN IMMEDIATE'); gate.record(con,418,{'Retry-After':'900'},'ban','u',b'ban'); con.commit(); con.close()
            code="from rate_control import RateGate; import sys; gate=RateGate(sys.argv[1]); scope=gate.request(); scope.__enter__()"
            child=subprocess.run([sys.executable,'-c',code,str(ledger)],cwd=Path(b.__file__).parent,capture_output=True,text=True,encoding='utf-8',env={**os.environ,'PYTHONUTF8':'1'})
            self.assertNotEqual(child.returncode,0)
            self.assertIn('HTTP=418',child.stderr)


class EmptyTests(unittest.TestCase):
    def test_sparse_response_span_does_not_resolve_empty_interval(self):
        with tempfile.TemporaryDirectory() as tmp:
            t=b.ms('2024-01-01T00:00:00Z'); store=b.Store(tmp)
            start,end=t+60000,t+120000
            store.note_empty('NEWUSDT','1m',start,end,t+180000,'empty',{},now_ms=100)
            def row(open_ms):
                return [open_ms,'1','1','1','1','0',open_ms+59999,'0',0,'0','0','0']
            store.ingest('NEWUSDT','1m',[row(t),row(end)],t+180000,'sparse')
            state,due=store.db.execute('SELECT state,next_check_ms FROM empty_ranges').fetchone()
            self.assertEqual(state,'pending_verification'); self.assertGreater(due,100)
            self.assertEqual(store.gaps('NEWUSDT','1m',t,t+180000),[(start,end)])
            store.db.close(); store=b.Store(tmp)
            self.assertEqual(store.db.execute('SELECT state FROM empty_ranges').fetchone()[0],'pending_verification')
            store.ingest('NEWUSDT','1m',[row(start)],t+180000,'actual-intersection')
            self.assertEqual(store.db.execute('SELECT state,next_check_ms FROM empty_ranges').fetchone(),('data_observed',0))
            self.assertEqual(store.gaps('NEWUSDT','1m',t,t+180000),[])
            store.db.close()
    def test_new_pair_metadata_and_automatic_recheck_after_deadline(self):
        with tempfile.TemporaryDirectory() as tmp:
            t=b.ms('2024-01-01T00:00:00Z'); store=b.Store(tmp)
            class Fake:
                def get(self,endpoint,**params):
                    if endpoint=='exchangeInfo': return {'symbols':[{'symbol':'NEWUSDT','status':'TRADING','isSpotTradingAllowed':True}]},'metadata'
                    if endpoint=='time': return {'serverTime':t+120000},'time'
                    return [[t,'1','1','1','1','0',t+59999,'0',0,'0','0','0']],'later'
            cfg={'pairs':[{'symbol':'NEWUSDT','enabled':True}],'page_limit':10,'empty_backoff_seconds':1,'empty_backoff_max_seconds':2}
            b.validate_metadata(Fake(),store,cfg)
            self.assertEqual(store.db.execute('SELECT symbol FROM metadata').fetchone()[0],'NEWUSDT')
            store.note_empty('NEWUSDT','1m',t,t+60000,t+120000,'empty',cfg,now_ms=int(time.time()*1000)-2000)
            store.db.close(); store=b.Store(tmp)
            b.download(Fake(),store,cfg,'NEWUSDT','1m',t,t+60000)
            self.assertEqual(store.gaps('NEWUSDT','1m',t,t+60000),[])
            self.assertEqual(store.db.execute('SELECT state FROM empty_ranges').fetchone()[0],'data_observed')
            store.db.close()

    def test_empty_persists_restart_force_and_later_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            t=b.ms('2024-01-01T00:00:00Z'); c={'page_limit':3,'empty_backoff_seconds':60,'empty_backoff_max_seconds':120}
            calls=[]
            class Fake:
                rows=[]
                def get(self,endpoint,**params):
                    calls.append(endpoint)
                    if endpoint=='time': return {'serverTime':t+120000},'clock'
                    return self.rows,'empty-raw'
            api=Fake(); s=b.Store(tmp)
            b.download(api,s,c,'NEWUSDT','1m',t,t+60000)
            saved=s.db.execute('SELECT start_ms,end_ms,raw_id,state,attempts FROM empty_ranges').fetchone()
            self.assertEqual(saved,(t,t+60000,'empty-raw','pending_verification',1))
            self.assertEqual(s.gaps('NEWUSDT','1m',t,t+60000),[(t,t+60000)])
            s.db.close(); s=b.Store(tmp); calls.clear()
            b.download(api,s,c,'NEWUSDT','1m',t,t+60000)
            self.assertEqual(calls,[])
            api.rows=[[t,'1','1','1','1','0.5',t+59999,'0.5',1,'0.5','0.5','0']]
            b.download(api,s,c,'NEWUSDT','1m',t,t+60000,force_recheck=True)
            self.assertEqual(s.gaps('NEWUSDT','1m',t,t+60000),[])
            self.assertEqual(s.db.execute('SELECT state FROM empty_ranges').fetchone()[0],'data_observed')
            self.assertEqual(s.db.execute('SELECT count(*) FROM empty_events').fetchone()[0],1)
            s.db.close()

    def test_bounded_backoff_expiry_and_partial_current_bucket(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=b.Store(tmp); t=b.ms('2024-01-01T00:00:00Z'); c={'empty_backoff_seconds':10,'empty_backoff_max_seconds':20}
            s.note_empty('NEWUSDT','1m',t,t+30000,t+30000,'a',c,now_ms=100000)
            self.assertEqual(s.db.execute('SELECT state FROM empty_ranges').fetchone()[0],'unclosed_absent')
            self.assertEqual(s.recheck_windows('NEWUSDT','1m',t,t+40000,now_ms=100001),[])
            self.assertEqual(s.recheck_windows('NEWUSDT','1m',t,t+120000,now_ms=100001),[(t+60000,t+120000)])
            self.assertEqual(s.recheck_windows('NEWUSDT','1m',t,t+30000,now_ms=110000),[(t,t+30000)])
            for n in range(5): s.note_empty('NEWUSDT','1m',t,t+30000,t+30000,'a',c,now_ms=200000+n*30000)
            observed,due=s.db.execute('SELECT observed_ms,next_check_ms FROM empty_ranges').fetchone()
            self.assertEqual(due-observed,20000)
            s.db.close()


if __name__=='__main__': unittest.main()
