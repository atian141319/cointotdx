import hashlib
import json
import struct
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from tools import lc1_audit as audit
from tools.verify import safe_child


class LC1Tests(unittest.TestCase):
    def test_native_samples_layout_calendar_and_tail_roundtrip(self):
        root=Path(audit.__file__).resolve().parents[1]
        report=json.loads((root/'validation'/'lc1-p0'/'native-format.json').read_text())
        total=0
        for sample in report:
            path=safe_child(root,sample['copy'])
            data=path.read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(),sample['source_sha256'])
            self.assertEqual(len(data)%32,0)
            rows=list(audit.LAYOUT.iter_unpack(data))
            self.assertEqual(b''.join(audit.LAYOUT.pack(*r) for r in rows),data)
            for row in rows:
                self.assertEqual(audit.encode_date(audit.decode_date(row[0])),row[0])
                self.assertLess(row[1],1440)
            total+=len(rows)
        self.assertEqual(total,9120)
        nonzero_tail=audit.LAYOUT.pack(45664,571,1,1,1,1,1,1,0x12345678)
        self.assertEqual(audit.LAYOUT.pack(*audit.LAYOUT.unpack(nonzero_tail)),nonzero_tail)

    def test_real_nonzero_tail_statistics_and_preservation(self):
        root=Path(audit.__file__).resolve().parents[1]/'validation'/'lc1-p0'/'native'
        for name in ('sh600000.lc1','sz000001.lc1'):
            self.assertTrue(all(row[-1]==0 for row in audit.LAYOUT.iter_unpack((root/name).read_bytes())))
        data=(root/'bj899050.lc1').read_bytes()
        rows=list(audit.LAYOUT.iter_unpack(data)); tails=[r[-1] for r in rows]
        self.assertEqual(len(tails),2400)
        self.assertTrue(all(tails))
        self.assertEqual(len(set(tails)),1262)
        self.assertEqual(tails[0],19660816)
        self.assertEqual(data[28:32].hex(),'10002c01')
        encoded=b''.join(audit.LAYOUT.pack(*row) for row in rows)
        self.assertEqual(encoded,data)
        self.assertEqual(encoded,(root/'bj899050.lc1.roundtrip').read_bytes())

    def test_float_error_and_range_are_explicit(self):
        result=audit.float_candidate('0.1')
        self.assertFalse(result['exact'])
        self.assertEqual(Decimal(result['signed_error']),Decimal('0.000000001490116119384765625'))
        self.assertIn('blocked',audit.float_candidate('1e100'))
        small=audit.float_candidate('1e-50')
        self.assertEqual(Decimal(small['candidate_float32_exact']),0)
        self.assertEqual(Decimal(small['relative_error']),-1)
        with self.assertRaises(ValueError): audit.encode_date(date(2040,1,1))

    def test_coin_candidates_do_not_truncate_volume_or_fabricate_tail(self):
        root=Path(audit.__file__).resolve().parents[1]/'validation'/'lc1-p0'
        for symbol in ('BTCUSDT','ETHUSDT'):
            rows=json.loads((root/(symbol+'.lc1.candidate.json')).read_text())
            self.assertEqual(len(rows),10)
            for row in rows:
                self.assertIsNone(row['volume']['candidate_u32'])
                self.assertIsNone(row['tail_u32'])
                self.assertFalse(row['full_lc1_record_generated'])
                self.assertFalse(row['volume']['unit_changed'])
                self.assertEqual(len(bytes.fromhex(row['prefix24_hex'])),24)


if __name__=='__main__': unittest.main()
