import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import bridge as b
from tools import verify


def manifest(root):
    entries=[]
    for file in sorted(root.rglob('*')):
        if file.is_file() and file.name!='PACKAGE-MANIFEST.json':
            entries.append({'path':file.relative_to(root).as_posix(),'size':file.stat().st_size,'sha256':hashlib.sha256(file.read_bytes()).hexdigest()})
    result={'files':entries,'source_version_sha256':'fixture',
            'offline_inputs':{'db':'database/market.sqlite3','raw_dir':'raw','export_dir':'export'}}
    path=root/'PACKAGE-MANIFEST.json'; path.write_text(json.dumps(result),encoding='utf-8')
    return path


def fixture(root):
    root.mkdir()
    t=b.ms('2024-01-01T00:00:00Z')
    row=[t,'0.00000001','0.00000001','0.00000001','0.00000001','0.12345678',t+59999,'9999999999.12345678',1,'0','0','0']
    raw=root/'raw'; raw.mkdir()
    def response(ident,data,url):
        body=json.dumps(data).encode()
        (raw/(ident+'.body')).write_bytes(body)
        (raw/(ident+'.json')).write_text(json.dumps({'url':url,'status':200,'body_sha256':hashlib.sha256(body).hexdigest()}),encoding='utf-8')
    url='https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=1m&startTime='+str(t)+'&endTime='+str(t+59999)
    response('old',[row],url)
    s=b.Store(root/'database'); s.ingest('BTCUSDT','1m',[row],t+60000,'old')
    corrected=row.copy(); corrected[5]='0.12345679'
    response('new',[corrected],url); s.ingest('BTCUSDT','1m',[corrected],t+60000,'new')
    response('empty',[],url.replace(str(t),str(t+60000)).replace(str(t+59999),str(t+119999)))
    s.note_empty('BTCUSDT','1m',t+60000,t+120000,t+180000,'empty',{},now_ms=100)
    s.db.close()
    c={'data_dir':str(root/'database'),'output_dir':str(root/'export'),'pairs':[{'symbol':'BTCUSDT'}],'intervals':['1m']}
    b.publish(c)
    source=Path(b.__file__).parent/'tools'
    tools=root/'tools'; tools.mkdir()
    for name in ('verify.py','offline_review.py'): shutil.copy2(source/name,tools/name)
    return manifest(root)


class OfflineTests(unittest.TestCase):
    def test_legacy_windows_manifest_paths_and_unsafe_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'package'; m=fixture(root)
            package=json.loads(m.read_text())
            for entry in package['files']: entry['path']=entry['path'].replace('/','\\')
            package['offline_inputs']['db']='database\\market.sqlite3'
            m.write_text(json.dumps(package),encoding='utf-8')
            result=verify.verify(verify.safe_child(root,package['offline_inputs']['db']),root/'raw',root/'export',m)
            self.assertEqual(result['result'],'VERIFIED_OFFLINE_EVIDENCE')
            self.assertEqual(verify.safe_child(root,'database\\market.sqlite3'),root/'database'/'market.sqlite3')
            for unsafe in ('/etc/passwd','C:\\file','C:/file','C:file','\\\\server\\share\\file','\\rooted','../escape','x/../../escape','x\\..\\..\\escape','x:stream',''):
                with self.subTest(path=unsafe), self.assertRaises(ValueError): verify.safe_child(root,unsafe)
            package['files'].append(dict(package['files'][0],path=package['files'][0]['path'].replace('\\','/')))
            m.write_text(json.dumps(package),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'Duplicate/case-colliding'):
                verify.verify(root/'database'/'market.sqlite3',root/'raw',root/'export',m)

    def test_fresh_copied_package_no_network_no_input_mutations(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp); initial=base/'original'; fixture(initial)
            fresh=base/'fresh'; shutil.copytree(initial,fresh)
            before={p.relative_to(fresh):p.read_bytes() for p in fresh.rglob('*') if p.is_file()}
            child=subprocess.run([sys.executable,'-B',str(fresh/'tools'/'offline_review.py'),'--package-dir',str(fresh),'--report-dir',str(base/'receipt')],capture_output=True,text=True,encoding='utf-8',timeout=10)
            self.assertEqual(child.returncode,0,child.stdout+child.stderr)
            report=json.loads((base/'receipt'/'offline-verification.json').read_text())
            self.assertTrue(report['database_readonly']); self.assertTrue(report['package_unchanged'])
            self.assertEqual(report['stored_rows'],1); self.assertEqual(report['revisions'],1); self.assertEqual(report['empty_events'],1)
            self.assertFalse(report['network_used'])
            after={p.relative_to(fresh):p.read_bytes() for p in fresh.rglob('*') if p.is_file()}
            self.assertEqual(before,after)

    def test_missing_db_fails_without_creation_and_bad_hash_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'package'; m=fixture(root)
            db=root/'database'/'market.sqlite3'; db.unlink()
            with self.assertRaises(FileNotFoundError): verify.verify(db,root/'raw',root/'export',m)
            self.assertFalse(db.exists())
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'package'; m=fixture(root)
            (root/'raw'/'new.body').write_bytes(b'[]')
            with self.assertRaisesRegex(ValueError,'hash/size mismatch'): verify.verify(root/'database'/'market.sqlite3',root/'raw',root/'export',m)

    def test_semantic_mismatch_detected_even_with_updated_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'package'; fixture(root)
            info_path=root/'raw'/'new.json'; info=json.loads(info_path.read_text()); info['url']=info['url'].replace('BTCUSDT','ETHUSDT'); info_path.write_text(json.dumps(info))
            m=manifest(root)
            with self.assertRaisesRegex(ValueError,'identity mismatch'): verify.verify(root/'database'/'market.sqlite3',root/'raw',root/'export',m)

    def test_report_inside_package_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'package'; fixture(root)
            child=subprocess.run([sys.executable,'-B',str(root/'tools'/'offline_review.py'),'--report-dir',str(root/'reports')],capture_output=True,text=True,timeout=10)
            self.assertNotEqual(child.returncode,0)
            self.assertFalse((root/'reports').exists())


if __name__=='__main__': unittest.main()
