import unittest, tempfile, json, csv, os, subprocess, logging
from pathlib import Path
from unittest.mock import patch
from io import BytesIO
from urllib.error import HTTPError, URLError
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import bridge as b

def bar(t, price='0.00000001', volume='0.12345678'):
    return [t,price,price,price,price,volume,t+59999,'123456789012345.12345678',0,'0','0','0']

class Tests(unittest.TestCase):
    def test_calendar(self):
        for x,y in [('2024-02-01T00:00:00Z','2024-03-01T00:00:00Z'),('2024-12-01T00:00:00Z','2025-01-01T00:00:00Z')]:
            self.assertEqual(b.next_time(b.ms(x),'1M'),b.ms(y))
        self.assertEqual(b.floor(b.ms('2024-02-29T23:59:00Z'),'1w'),b.ms('2024-02-26T00:00:00Z'))
    def test_idempotent_revision_current_and_gap(self):
        with tempfile.TemporaryDirectory() as directory:
            s=b.Store(directory); t=b.ms('2024-02-29T23:59:00Z')
            s.ingest('BTCUSDT','1m',[bar(t)],t+30000,'a')
            self.assertEqual(s.db.execute('SELECT final FROM bars').fetchone()[0],0)
            s.ingest('BTCUSDT','1m',[bar(t)],t+60000,'b')
            s.ingest('BTCUSDT','1m',[bar(t)],t+60000,'c')
            self.assertEqual(s.db.execute('SELECT count(*) FROM revisions').fetchone()[0],0)
            s.ingest('BTCUSDT','1m',[bar(t,'0.00000002')],t+60000,'d')
            self.assertEqual(s.db.execute('SELECT count(*) FROM revisions').fetchone()[0],1)
            s.ingest('BTCUSDT','1m',[bar(t+120000)],t+180000,'e')
            self.assertEqual(s.gaps('BTCUSDT','1m',t,t+180000),[(t+60000,t+120000)])
            with self.assertRaises(ValueError): s.ingest('BTCUSDT','1m',[bar(t)],t,'f')
            s.db.close()
    def test_incomplete_and_weekend(self):
        t=b.ms('2024-03-02T00:00:00Z'); rows=[bar(t+i*60000) for i in range(5)]
        result=b.aggregate(rows,'5m',t+300000)[0]
        self.assertTrue(result['complete']); self.assertEqual(result['base_volume'],'0.61728390')
        self.assertFalse(b.aggregate(rows[:2]+rows[3:],'5m',t+300000)[0]['complete'])
        self.assertFalse(b.aggregate(rows,'5m',t+200000)[0]['complete'])
        with self.assertRaises(b.Inexact): b.aggregate([bar(t,volume='1'+'0'*81+'.1')],'5m',t+300000)
    def test_pagination_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            s=b.Store(directory); t=b.ms('2024-01-01T00:00:00Z')
            class Fake:
                def get(self,endpoint,**params):
                    if endpoint=='time': return {'serverTime':t+300000},'clock'
                    start=params['startTime']; return [bar(start)],str(start)
            b.download(Fake(),s,{'page_limit':1},'BTCUSDT','1m',t,t+180000)
            self.assertEqual(s.db.execute('SELECT count(*) FROM bars').fetchone()[0],3)
            self.assertEqual(s.db.execute('SELECT next_ms FROM progress').fetchone()[0],t+180000)
            s.db.close()
            s=b.Store(directory)
            self.assertEqual(s.gaps('BTCUSDT','1m',t,t+240000),[(t+180000,t+240000)])
            s.db.close()
    def test_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            with b.Instance(directory):
                with self.assertRaises(RuntimeError):
                    with b.Instance(directory): pass
            with b.Instance(directory): pass
    def test_atomic_publication_and_exact_read(self):
        with tempfile.TemporaryDirectory() as directory:
            c={'data_dir':directory+'/data','output_dir':directory+'/out','pairs':[{'symbol':'BTCUSDT'}],'intervals':['1m']}
            s=b.Store(c['data_dir']); t=b.ms('2024-01-01T00:00:00Z'); s.ingest('BTCUSDT','1m',[bar(t)],t+60000,'a'); s.db.close()
            b.publish(c); pointer=Path(c['output_dir'])/'CURRENT.json'; old=pointer.read_bytes()
            batch=json.loads(old)['batch']
            with (Path(c['output_dir'])/batch/'BTCUSDT-minute-1.csv').open(newline='') as f: row=next(csv.DictReader(f))
            self.assertEqual(row['base_volume'],'0.12345678'); self.assertEqual(row['quote_volume'],'123456789012345.12345678')
            with patch('bridge.os.replace',side_effect=PermissionError('file busy')):
                with self.assertRaises(PermissionError): b.publish(c)
            self.assertEqual(pointer.read_bytes(),old)

            with patch('bridge.csv.writer',side_effect=OSError('disk full')):
                with self.assertRaises(OSError): b.publish(c)
            self.assertEqual(pointer.read_bytes(),old)

    def test_retry_and_stop_conditions(self):
        with tempfile.TemporaryDirectory() as directory:
            c={'data_dir':directory,'base_url':b.HOSTS[0],'retries':2,'timeout_seconds':1,'request_spacing_seconds':0.1}
            clock=[100.0]
            api=b.API(c,rate_path=Path(directory)/'rate.sqlite3',now=lambda:clock[0])
            class Reply:
                status=200; headers={}
                def __enter__(self): return self
                def __exit__(self,*args): pass
                def read(self): return b'{}'
            error=HTTPError('https://data-api.binance.vision',429,'limited',{'Retry-After':'7'},BytesIO(b'limited'))
            def advance(seconds,stop): clock[0]+=seconds
            with patch.object(api.opener,'open',side_effect=[error,Reply()]) as opened, patch('bridge.cancellable_wait',side_effect=advance) as waited:
                self.assertEqual(api.get('ping')[0],{})
                self.assertEqual(opened.call_count,2)
                self.assertIn(7,[call.args[0] for call in waited.call_args_list])
            for code in (403,418,451):
                api=b.API(c,rate_path=Path(directory)/(str(code)+'.sqlite3'))
                with patch.object(api.opener,'open',side_effect=HTTPError('u',code,'blocked',{},BytesIO(b'blocked'))) as opened:
                    with self.assertRaises(b.Halt): api.get('ping')
                    with self.assertRaises(b.Halt): api.get('ping')
                    self.assertEqual(opened.call_count,1)
            api=b.API(c,rate_path=Path(directory)/'offline.sqlite3')
            with patch.object(api.opener,'open',side_effect=URLError('offline')) as opened, patch('bridge.cancellable_wait'):
                with self.assertRaises(RuntimeError): api.get('ping')
                self.assertEqual(opened.call_count,3)
            Path(directory,'STOP').write_text('stop')
            with self.assertRaises(b.Stopped): b.API(c,rate_path=Path(directory)/'stop.sqlite3').get('ping')

    def test_finalization_clock_precedes_fetch(self):
        with tempfile.TemporaryDirectory() as directory:
            s=b.Store(directory); t=b.ms('2024-03-02T00:00:00Z'); calls=[]
            class Fake:
                def get(self,endpoint,**params):
                    calls.append(endpoint)
                    if endpoint=='time': return {'serverTime':t+59000},'clock'
                    return [bar(t)],'kline'
            b.download(Fake(),s,{'page_limit':1},'BTCUSDT','1m',t,t+60000)
            self.assertEqual(calls,['time','klines'])
            self.assertEqual(s.db.execute('SELECT final FROM bars').fetchone()[0],0)
            s.db.close()

    def test_windows_period_file_names_do_not_collide(self):
        with tempfile.TemporaryDirectory() as directory:
            c={'data_dir':directory+'/data','output_dir':directory+'/out','pairs':[{'symbol':'BTCUSDT'}],'intervals':list(b.INTERVALS)}
            b.publish(c)
            batch=json.loads((Path(c['output_dir'])/'CURRENT.json').read_text())['batch']
            manifest=json.loads((Path(c['output_dir'])/batch/'manifest.json').read_text())
            names=[x['name'].casefold() for x in manifest['files']]
            self.assertEqual(len(names),len(set(names)))
            for entry in manifest['files']:
                self.assertEqual(b.hashlib.sha256((Path(c['output_dir'])/batch/entry['name']).read_bytes()).hexdigest(),entry['sha256'])

    def test_process_exit_releases_lock_and_rolls_back_uncommitted_page(self):
        with tempfile.TemporaryDirectory() as directory:
            s=b.Store(directory); s.db.close()
            child_code="import bridge,sys,os; lock=bridge.Instance(sys.argv[1]); lock.__enter__(); s=bridge.Store(sys.argv[1]); s.db.execute('BEGIN'); s.db.execute(\"INSERT INTO progress VALUES('BTCUSDT','1m',123)\"); os._exit(9)"
            child=subprocess.run([sys.executable,'-c',child_code,directory],cwd=Path(b.__file__).parent,capture_output=True)
            self.assertEqual(child.returncode,9,child.stderr)
            with b.Instance(directory):
                s=b.Store(directory)
                self.assertEqual(s.db.execute('SELECT count(*) FROM progress').fetchone()[0],0)
                self.assertEqual(s.db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
                s.db.close()

    def test_second_process_cannot_enter_existing_instance(self):
        with tempfile.TemporaryDirectory() as directory:
            code="import bridge,sys; lock=bridge.Instance(sys.argv[1]); lock.__enter__()"
            with b.Instance(directory):
                child=subprocess.run([sys.executable,'-c',code,directory],cwd=Path(b.__file__).parent,capture_output=True)
                self.assertNotEqual(child.returncode,0)
            with b.Instance(directory): pass

    def test_configuration_reload_pauses_and_removes_without_deleting_history(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg=json.loads((Path(b.__file__).parent/'config.smoke.json').read_text())
            cfg.update(data_dir=directory+'/data',output_dir=directory+'/out',sync_seconds=0.01)
            cfg_path=Path(directory)/'config.json'; cfg_path.write_text(json.dumps(cfg))
            s=b.Store(cfg['data_dir']); t=b.ms('2024-01-01T00:00:00Z'); s.ingest('BTCUSDT','1m',[bar(t)],t+60000,'fixture'); s.db.close()
            seen=[]
            def fake_sync(c):
                seen.append([p['symbol'] for p in c['pairs'] if p.get('enabled',True)])
                if len(seen)==1:
                    cfg['pairs'][0]['enabled']=False; cfg_path.write_text(json.dumps(cfg))
                elif len(seen)==2:
                    cfg['pairs']=cfg['pairs'][1:]; cfg_path.write_text(json.dumps(cfg))
                else: Path(c['data_dir'],'STOP').write_text('stop')
            with patch.object(sys,'argv',['bridge.py','run','--config',str(cfg_path)]),patch('bridge.synchronize',side_effect=fake_sync),patch('bridge.publish'),patch('bridge.logging.FileHandler',return_value=logging.NullHandler()),patch('bridge.logging.basicConfig'):
                b.main()
            self.assertEqual(seen,[['BTCUSDT','ETHUSDT'],['ETHUSDT'],['ETHUSDT']])
            s=b.Store(cfg['data_dir']); self.assertEqual(s.db.execute("SELECT count(*) FROM bars WHERE symbol='BTCUSDT'").fetchone()[0],1); s.db.close()
if __name__=='__main__': unittest.main()
