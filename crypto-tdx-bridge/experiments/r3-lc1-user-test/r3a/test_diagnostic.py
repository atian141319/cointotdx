import importlib.util
import json
import shutil
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('r3a',Path(__file__).with_name('diagnostic.py'))
d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)


class DiagnosticTests(unittest.TestCase):
    def test_three_controls_keep_paths_and_B_changes_only_time(self):
        for code in d.CODES:
            native=(d.PROJECT/'validation/lc1-p0/native/sh600000.lc1').read_bytes()
            real=(d.TRIAL/'samples/update'/('sh'+code+'.lc1')).read_bytes()
            a=(d.HERE/'samples/A'/('sh'+code+'.lc1')).read_bytes()
            b=(d.HERE/'samples/B'/('sh'+code+'.lc1')).read_bytes()
            c=(d.HERE/'samples/C'/('sh'+code+'.lc1')).read_bytes()
            self.assertEqual(a,native);self.assertEqual(c,real)
            self.assertEqual(len(b),len(c))
            for offset in range(0,len(b),32):self.assertEqual(b[offset+4:offset+32],c[offset+4:offset+32])
            observed=d.minute_report(b)['rows']
            self.assertTrue(all(r['weekday']==0 and r['unzoned_time'].startswith('2026-06-08T09:') for r in observed))
            self.assertEqual(observed[0]['minute_u16'],571)
            self.assertEqual(observed[-1]['minute_u16'],580)

    def test_backup_and_native_day_control_hashes_match(self):
        for entry in json.loads((d.HERE/'backup/manifest.json').read_text(encoding='utf-8')):
            if entry['existed_before']:
                self.assertEqual(d.sha((d.HERE/'backup'/entry['path']).read_bytes()),entry['sha256'])
        reference=json.loads((d.HERE/'samples/references.json').read_text(encoding='utf-8'))
        day=(d.HERE/'samples/native-day-control.day').read_bytes()
        self.assertEqual(d.sha(day),reference['native_day']['sha256'])
        self.assertEqual(len(day)%32,0)

    def test_invalid_length_and_time_are_rejected(self):
        with self.assertRaises(ValueError):d.minute_report(b'bad')
        invalid=d.LC1.pack(45664,1440,1,1,1,1,1,1,0)
        with self.assertRaises(ValueError):d.minute_report(invalid)

    def test_switches_and_restore_preserve_preexisting_trial_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);client=base/'client';here=base/'r3a'
            client.mkdir();here.mkdir()
            registry=bytearray(50+2*360)
            for index,code in enumerate(d.CODES):registry[50+index*360:56+index*360]=code.encode()
            originals={d.REGISTRY:bytes(registry),'T0002/hq_cache/sh.tcu':bytes(308),
                       'T0002/hq_cache/sh.th2':bytes(1032),'T0002/hq_cache/sh.tfz':bytes(10),
                       'T0002/blocknew/zxg.blk':b'original user watchlist\r\n'}
            for code in d.CODES:
                originals['vipdoc/sh/minline/sh'+code+'.lc1']=(d.HERE/'samples/C'/('sh'+code+'.lc1')).read_bytes()
            for rel,data in originals.items():
                dest=client/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
            shutil.copytree(d.HERE/'samples',here/'samples')
            entries=[]
            for rel in d.CONFIGS+d.DATA:
                exists=rel in originals
                entries.append({'path':rel,'existed_before':exists,'sha256':d.sha(originals[rel]) if exists else None})
                if exists:
                    dest=here/'backup'/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(originals[rel])
            d.write_json(here/'backup/manifest.json',entries)
            publisher=d.r3();publisher.HERE=base;publisher.CLIENT=client;publisher.no_client=lambda:None
            with patch.object(d,'HERE',here),patch.object(d,'CLIENT',client),patch.object(d,'closed'),patch.object(d,'r3',return_value=publisher):
                d.apply('A')
                self.assertEqual((client/'vipdoc/sh/minline/sh999006.lc1').read_bytes(),(here/'samples/A/sh999006.lc1').read_bytes())
                self.assertEqual((client/'T0002/blocknew/zxg.blk').read_bytes(),b'1999006\r\n1999007\r\n')
                d.apply('B');d.apply('C');d.restore()
            for rel,data in originals.items():self.assertEqual((client/rel).read_bytes(),data)
            self.assertFalse((client/'vipdoc/sh/lday/sh999006.day').exists())


if __name__=='__main__':unittest.main()
