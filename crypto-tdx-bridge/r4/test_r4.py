import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).parent))
from live_store import LiveStore, InboxWriter
from settings import default_settings, save, load, validate, registration_check
from streams import names
from streams import ControlLimit, Receiver
import queue
import websocket
from display import Publisher, encode


def event(moment=100,volume='0.6',closed=False):
    return {'e':'kline','E':1790852700000+moment,'s':'BTCUSDT','k':{
        's':'BTCUSDT','i':'1m','t':1790852700000,'T':1790852759999,
        'o':'1.01','h':'1.03','l':'1','c':'1.02','v':volume,'q':'12.34567890',
        'n':int(moment),'L':int(moment),'V':'0.1','Q':'1.001','B':'0','x':closed}}


class LiveTests(unittest.TestCase):
    def test_cumulative_not_added_and_duplicate_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            store=LiveStore(temp);writer=InboxWriter(temp)
            try:
                for message in (event(100,'0.6'),event(200,'1.5'),event(200,'1.5')):
                    identity=writer.add(message,'test');store.apply(identity,message)
                row=store.db.execute('SELECT payload FROM bars').fetchone()
                self.assertEqual(json.loads(row[0])[5],'1.5')
                self.assertEqual(store.db.execute('SELECT count(*) FROM bars').fetchone()[0],1)
                self.assertEqual(store.db.execute("SELECT count(*) FROM live_decisions WHERE reason='duplicate_snapshot'").fetchone()[0],1)
            finally:writer.close();store.close()

    def test_older_events_and_final_regression_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            store=LiveStore(temp)
            try:
                store.apply('first',event(200,'1.5'))
                store.apply('old',event(100,'0.6'))
                store.apply('close',event(300,'2.5',True))
                store.apply('late',event(400,'4.5',False))
                value,final=store.db.execute('SELECT payload,final FROM bars').fetchone()
                self.assertEqual(json.loads(value)[5],'2.5');self.assertEqual(final,1)
                self.assertEqual(store.db.execute('SELECT count(*) FROM revisions').fetchone()[0],1)
            finally:store.close()

    def test_durable_buffer_survives_reopen_and_closed_revision_is_saved(self):
        with tempfile.TemporaryDirectory() as temp:
            store=LiveStore(temp);writer=InboxWriter(temp)
            identity=writer.add(event(100,'1.1',True),'before-history');writer.close();store.close()
            reopened=LiveStore(temp)
            try:
                self.assertEqual(len(reopened.pending()),1)
                reopened.apply(identity,json.loads(reopened.pending()[0][1]))
                reopened.apply('correction',event(200,'1.2',True))
                self.assertEqual(reopened.db.execute('SELECT count(*) FROM revisions').fetchone()[0],1)
                self.assertEqual(json.loads(reopened.db.execute('SELECT payload FROM bars').fetchone()[0])[5],'1.2')
            finally:reopened.close()

    def test_duplicate_advances_order_watermark(self):
        with tempfile.TemporaryDirectory() as temp:
            store=LiveStore(temp)
            try:
                first=event(100);second=copy.deepcopy(first);second['E']+=100
                store.apply('one',first);store.apply('duplicate',second)
                late=copy.deepcopy(first);late['E']+=50;late['k']['c']='1.025'
                store.apply('late-conflict',late)
                self.assertEqual(json.loads(store.db.execute('SELECT payload FROM bars').fetchone()[0])[4],'1.02')
            finally:store.close()


class ConfigurationTests(unittest.TestCase):
    def test_roundtrip_and_market_code_conflict(self):
        with tempfile.TemporaryDirectory() as temp:
            c=default_settings();path=Path(temp)/'settings.json';save(path,c);self.assertEqual(load(path),c)
            c['pairs'].append(dict(c['pairs'][0],symbol='ETHUSDT'))
            with self.assertRaises(ValueError):validate(c)

    def test_month_stream_case_and_all_eight_periods(self):
        streams=names(default_settings()['pairs'])
        self.assertEqual(len(streams),8)
        self.assertIn('btcusdt@kline_1m',streams);self.assertIn('btcusdt@kline_1M',streams)
        self.assertIn('btcusdt@kline_1h',streams)

    def test_symbol_identity_not_merely_registered_name(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);c=default_settings();c['tdx']['installation']=str(root)
            registry=root/'T0002/lc/lcext.lei';registry.parent.mkdir(parents=True)
            record=bytearray(320);record[:6]=b'397901';record[7:14]=b'ETHUSDT';registry.write_bytes(record)
            self.assertFalse(registration_check(c,c['pairs'][0])[0])

    def test_native_collision_is_rejected_before_external_registration(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);c=default_settings();c['tdx']['installation']=str(root)
            tnf=root/'T0002/hq_cache/szs.tnf';tnf.parent.mkdir(parents=True)
            raw=bytearray(410);raw[50:56]=b'397901';tnf.write_bytes(raw)
            allowed,reason=registration_check(c,c['pairs'][0])
            self.assertFalse(allowed);self.assertIn('collides',reason)

    def test_stop_cancels_pending_configuration_reload(self):
        from desktop import Desktop
        ui=Desktop.__new__(Desktop);ui.reload_requested=True;ui.engine=None
        ui.messages=queue.Queue();ui.stop();ui.reload_wait()
        self.assertFalse(ui.reload_requested)

    def test_fraction_loss_explicit_and_uint_overflow_rejected(self):
        row=[1790852700000,'1.01','1.03','1','1.02','0.6',1790852759999,'12.34567890',1,'0','0','0']
        data,errors=encode(row);self.assertEqual(len(data),32)
        self.assertEqual(errors['base_volume']['error'],'-0.6')
        row[5]='4294967296'
        with self.assertRaises(ValueError):encode(row)

    def test_busy_file_stays_pending_and_retry_commits(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);c=default_settings();c['data_directory']=str(root/'precise')
            c['tdx']={'installation':str(root/'client'),'data_directory':str(root/'client/vipdoc'),'executable':''}
            registry=root/'client/T0002/lc/lcext.lei';registry.parent.mkdir(parents=True)
            record=bytearray(320);record[:6]=b'397901';record[7:14]=b'BTCUSDT';registry.write_bytes(record)
            publisher=Publisher(c,lambda **x:None)
            row=[1790852700000,'1.01','1.03','1','1.02','0.6',1790852759999,'12.34567890',1,'0','0','0']
            publisher.queue(c['pairs'][0],'1m',[row])
            actual_replace=__import__('os').replace
            def busy(source,target):
                if str(target).endswith('.lc1'):raise PermissionError('client holds file')
                return actual_replace(source,target)
            with patch('display.os.replace',busy):self.assertFalse(publisher.flush())
            self.assertTrue(any(publisher.pending.values()));self.assertTrue(publisher.flush())
            self.assertFalse(any(publisher.pending.values()))

    def test_interrupted_batch_recovers_previous_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);c=default_settings();c['data_directory']=str(root/'precise')
            c['tdx']['data_directory']=str(root/'client/vipdoc')
            target=root/'client/vipdoc/sz/minline/sz397901.lc1'
            target.parent.mkdir(parents=True);target.write_bytes(b'new')
            journal=root/'precise/display/batches/interrupted';journal.mkdir(parents=True)
            (journal/'rollback-0.bin').write_bytes(b'old')
            (journal/'receipt.json').write_text(json.dumps({'state':'PREPARED','files':[{
                'path':str(target),'old_exists':True,'rollback_file':'rollback-0.bin',
                'old_sha256':__import__('hashlib').sha256(b'old').hexdigest()}]}))
            Publisher(c,lambda **x:None)
            self.assertEqual(target.read_bytes(),b'old')
            self.assertEqual(json.loads((journal/'receipt.json').read_text())['state'],'ROLLED_BACK_AFTER_INTERRUPTION')


class StreamLifecycleTests(unittest.TestCase):
    def test_control_limit_counts_only_outbound_calls(self):
        clock=[0.0];sleeps=[]
        def sleep(seconds):sleeps.append(seconds);clock[0]+=seconds
        gate=ControlLimit()
        with patch('streams.time.monotonic',lambda:clock[0]),patch('streams.time.sleep',sleep):
            for _ in range(5):gate.acquire()
        self.assertEqual(sleeps,[1.0])
        self.assertEqual(len(gate.times),1)

    def test_server_shutdown_reconnects_without_guessing_interfaces(self):
        with tempfile.TemporaryDirectory() as temp:
            store=LiveStore(temp);store.close()
            c=default_settings();c['data_directory']=temp
            notifications=queue.Queue();receiver=Receiver(c,lambda **x:None,notifications)
            class Socket:
                pongs=0
                messages=[{'id':1,'result':None},{'e':'serverShutdown'}]
                def recv_data_frame(self,control_frame):
                    return websocket.ABNF.OPCODE_TEXT,type('Frame',(),{'data':json.dumps(self.messages.pop(0))})()
                def close(self):pass
            attempts=[]
            def connect(config):
                attempts.append(1)
                if len(attempts)==1:return Socket()
                receiver.stopping.set();raise ConnectionError('test complete')
            with patch('streams.open_socket',connect),patch.object(receiver.stopping,'wait',lambda timeout:False):
                receiver.run()
            events=list(notifications.queue)
            self.assertEqual(len(attempts),2)
            self.assertTrue(any('serverShutdown' in detail for _,detail in events))

    def test_connection_rotates_before_twenty_four_hours(self):
        with tempfile.TemporaryDirectory() as temp:
            store=LiveStore(temp);store.close()
            c=default_settings();c['data_directory']=temp;c['rotation_seconds']=60
            notifications=queue.Queue();receiver=Receiver(c,lambda **x:None,notifications)
            class Socket:
                def close(self):pass
            attempts=[]
            def connect(config):
                attempts.append(1)
                if len(attempts)==1:return Socket()
                receiver.stopping.set();raise ConnectionError('test complete')
            with patch('streams.open_socket',connect),patch('streams.time.monotonic',side_effect=[0,61,62]),patch.object(receiver.stopping,'wait',lambda timeout:False):
                receiver.run()
            self.assertTrue(any('Scheduled connection rotation' in detail for _,detail in list(notifications.queue)))


class OfflineReviewTests(unittest.TestCase):
    def test_readonly_wal_snapshot_creates_no_sidecars(self):
        from verify_evidence import verify
        import hashlib
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);snapshot=root/'snapshot';snapshot.mkdir()
            db=sqlite3.connect(snapshot/'market.sqlite3')
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('CREATE TABLE live_inbox(payload TEXT,raw_path TEXT);'
                'CREATE TABLE bars(symbol TEXT,interval TEXT,open_ms INTEGER,payload TEXT,raw_id TEXT);')
            db.close()
            display=snapshot/'display';display.mkdir()
            for name in ('sz397901.lc1','sz397901.lc5','sz397901.day'):(display/name).write_bytes(b'')
            entries=[{'path':p.relative_to(root).as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in root.rglob('*') if p.is_file()]
            (root/'manifest.json').write_text(json.dumps({'files':entries,'observed_ms':0}))
            before={p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()}
            self.assertEqual(verify(root)['failures'],[])
            after={p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()}
            self.assertEqual(before,after)


if __name__=='__main__':unittest.main()
