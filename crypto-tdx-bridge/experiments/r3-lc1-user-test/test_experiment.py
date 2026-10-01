import importlib.util
import json
import struct
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('r3',Path(__file__).with_name('experiment.py'))
r3=importlib.util.module_from_spec(spec); spec.loader.exec_module(r3)


class TrialTests(unittest.TestCase):
    def row(self):
        return [1790467440000,'0.1','0.2','0.01','0.15','0.52927000',1790467499999,'44646.1',1,'0','0','0']

    def test_trial_layout_exact_errors_and_explicit_zero_volume(self):
        data,report=r3.pack_row(self.row()); decoded=r3.LAYOUT.unpack(data)
        self.assertEqual(len(data),32)
        self.assertEqual(decoded[:2],((2026-2004)*2048+9*100+27,4))
        self.assertEqual(decoded[-2:],(0,0))
        self.assertTrue(report['volume']['positive_quantity_became_zero'])
        self.assertEqual(Decimal(report['volume']['truncated_quantity']),Decimal('0.52927'))
        self.assertNotEqual(Decimal(report['float_fields']['open']['signed_rounding_error']),0)
        self.assertEqual(r3.LAYOUT.pack(*decoded),data)

    def test_ranges_and_invalid_values_rejected_without_scaling(self):
        for index,value in ((5,'4294967296'),(5,'-1'),(1,'1e50')):
            row=self.row(); row[index]=value
            with self.assertRaises((ValueError,OverflowError)): r3.pack_row(row)

    def test_second_file_failure_restores_first_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp); client=base/'client'; client.mkdir()
            (client/'first').write_bytes(b'previous')
            original=r3.os.replace
            def fail_second(source,destination):
                if Path(destination).name=='second': raise PermissionError('file occupied')
                return original(source,destination)
            with patch.object(r3,'HERE',base),patch.object(r3,'CLIENT',client),patch.object(r3,'no_client'),patch.object(r3.os,'replace',side_effect=fail_second):
                with self.assertRaises(PermissionError): r3.replace_group({'first':b'new','second':b'new'},'test')
            self.assertEqual((client/'first').read_bytes(),b'previous')
            self.assertFalse((client/'second').exists())

    def test_restore_recovers_configs_and_removes_only_trial_added_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp); client=base/'client'; backup=base/'backup/client-before-trial'
            client.mkdir(); backup.mkdir(parents=True); (base/'evidence').mkdir()
            (backup/'setting.cfg').write_bytes(b'original config')
            (client/'setting.cfg').write_bytes(b'changed config')
            (client/'trial.lc1').write_bytes(b'trial')
            baseline=r3.inventory(backup)
            r3.write_json(base/'evidence/baseline-manifest.json',baseline)
            outside=base/'unrelated'; outside.write_bytes(b'keep')
            with patch.object(r3,'HERE',base),patch.object(r3,'CLIENT',client),patch.object(r3,'BASELINE',backup),patch.object(r3,'no_client'):
                r3.restore()
            self.assertEqual(r3.inventory(client),baseline)
            self.assertEqual(outside.read_bytes(),b'keep')


if __name__=='__main__': unittest.main()
