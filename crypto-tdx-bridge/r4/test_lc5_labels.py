from datetime import datetime, timezone
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from display import Publisher, encode, decode_time
from settings import default_settings, validate
from session_config import CONTINUOUS_05


def row(utc):
    start = int(datetime.fromisoformat(utc).timestamp() * 1000)
    return [start,'2686.01','2689.55','2684.66','2687.94','0.75',start+299999,
            '2015.123456',9,'0.1','12','0']


class LabelTests(unittest.TestCase):
    def test_source_derived_label_roundtrip_at_calendar_boundaries(self):
        for date in ('2024-02-29T23:55:00+00:00','2026-09-30T23:55:00+00:00',
                     '2026-12-31T23:55:00+00:00'):
            original = row(date)
            raw,_ = encode(original,interval='5m',minute_label='last_minute')
            self.assertEqual(struct.unpack_from('<HH',raw)[1],1439)
            self.assertEqual(decode_time(raw,False,interval='5m',minute_label='last_minute'),original[0])
            unchanged,_ = encode(original)
            self.assertEqual(raw[4:],unchanged[4:])
            self.assertEqual(struct.unpack_from('<HH',unchanged)[1],1435)

    def test_repeated_updates_and_restart_never_accumulate_offset_or_append_duplicate(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);client=root/'client';cache=client/'T0002/hq_cache'
            cache.mkdir(parents=True)
            (cache/'ds_tinf.dat').write_bytes(bytes([10])+b'?'*8+b'\0'+struct.pack('<10HI',*CONTINUOUS_05,1))
            config={'data_directory':str(root/'exact'),'tdx':{'installation':str(client),'data_directory':str(client/'vipdoc')},
                    'pairs':[{'symbol':'ETHUSDT','market':'ds','market_id':10,'code':'397903','lc5_time_label':'last_minute'}]}
            pair=config['pairs'][0];original=row('2026-09-30T00:00:00+00:00')
            with patch('display.registration_check',return_value=(True,'test')):
                first=Publisher(config,lambda **x:None)
                first.queue(pair,'5m',[original]);self.assertTrue(first.flush())
                original[4]='2688.12'
                second=Publisher(config,lambda **x:None)
                second.queue(pair,'5m',[original]);self.assertTrue(second.flush())
                second.queue(pair,'5m',[original]);self.assertFalse(second.flush())
                raw=second.targets(pair)['5m'].read_bytes()
                self.assertEqual(len(raw),32)
                self.assertEqual(struct.unpack_from('<HH',raw)[1],4)
                self.assertEqual(decode_time(raw,False,interval='5m',minute_label='last_minute'),original[0])
                self.assertEqual(len(second.cache[second.targets(pair)['5m']]),1)

    def test_wrong_cache_phase_and_invalid_source_or_context_fail_closed(self):
        original=row('2026-09-30T00:00:00+00:00')
        raw,_=encode(original)
        with self.assertRaises(ValueError):
            decode_time(raw,False,interval='5m',minute_label='last_minute')
        original[0]+=60000
        with self.assertRaises(ValueError):
            encode(original,interval='5m',minute_label='last_minute')
        c=default_settings();c['pairs']=[{'symbol':'ETHUSDT','display_name':'ETH','code':'397903',
            'market':'ds','market_id':10,'enabled':True,'history_start':'2026-09-30T00:00:00Z',
            'lc5_time_label':'last_minute','display_context_start':'2026-09-29T23:00:00Z'}]
        validate(c,check_paths=False)
        c['pairs'][0]['display_context_start']='2026-09-30T00:00:00Z'
        with self.assertRaises(ValueError):
            validate(c,check_paths=False)


if __name__ == '__main__':
    unittest.main()
