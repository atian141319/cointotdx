import json
from pathlib import Path
import sys
import unittest
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import multi


def minute(time, volume='0.6', amount='123456789.12345678'):
    return [time, '0.00000010', '0.00000030', '0.00000005', '0.00000020',
            volume, time + 59999, amount, 1, '0.1', '1.00000000', '0']


class AggregationTests(unittest.TestCase):
    def test_sum_exact_before_trial_truncation(self):
        rows = [minute(multi.START + i * 60000) for i in range(5)]
        candles, incomplete = multi.aggregate(rows, 5)
        self.assertFalse(incomplete)
        self.assertEqual(candles[0][5], '3.0')  # int(.6) per minute would give zero.
        self.assertEqual(candles[0][7], '617283945.61728390')
        self.assertEqual(candles[0][2:5], ['0.00000030', '0.00000005', '0.00000020'])

    def test_absent_or_duplicate_minute_never_complete(self):
        rows = [minute(multi.START + i * 60000) for i in (0, 1, 3, 4)]
        candles, incomplete = multi.aggregate(rows, 5)
        self.assertEqual(candles, [])
        self.assertEqual(len(incomplete), 1)
        rows.append(rows[0])
        self.assertEqual(multi.aggregate(rows, 5)[0], [])

    def test_weekend_midnight_and_full_hour_boundaries(self):
        start = multi.bridge.ms('2026-09-26T23:00:00Z')
        rows = [minute(start + i * 60000) for i in range(120)]
        for period, expected in ((5, 24), (15, 8), (30, 4), (60, 2)):
            candles, incomplete = multi.aggregate(rows, period)
            self.assertEqual(len(candles), expected)
            self.assertFalse(incomplete)
            self.assertEqual(candles[0][0], start)
            self.assertEqual(candles[-1][6], start + 120 * 60000 - 1)

    def test_initial_update_and_restore_keep_working_lc1(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trial = multi.diagnostic.r3()
            client = root / 'client'
            registry = client / 'T0002/lc/lcext.lei'
            registry.parent.mkdir(parents=True)
            registry.write_bytes(b'397901\x00BTCUSDT\x00')
            lc1 = client / multi.PATHS[0]
            lc1.parent.mkdir(parents=True)
            original = trial.pack_row(minute(multi.START))[0]
            lc1.write_bytes(original)
            trial.CLIENT = client
            trial.HERE = root / 'transaction-engine'
            trial.HERE.mkdir()
            trial.no_client = lambda: None
            here = root / 'experiment'
            here.mkdir()
            store = multi.bridge.Store(here / 'data')
            store.ingest('BTCUSDT', '1m', [minute(multi.START + i * 60000)
                for i in range(2880)], multi.UPDATE_END, 'unit-test-raw')
            store.db.close()
            with patch.object(multi, 'HERE', here), patch.object(multi, 'CLIENT', client), \
                    patch.object(multi.diagnostic, 'closed', lambda: None), \
                    patch.object(multi.diagnostic, 'r3', lambda: trial):
                multi.publish(multi.INITIAL_END)
                lc5 = client / multi.PATHS[1]
                self.assertEqual(len(lc1.read_bytes()) // 32, 1440)
                self.assertEqual(len(lc5.read_bytes()) // 32, 288)
                first = multi.diagnostic.LC1.unpack(lc5.read_bytes()[:32])
                self.assertEqual(first[7], 3)  # Aggregate .6 * 5 before truncating.
                multi.publish(multi.UPDATE_END)
                self.assertEqual(len(lc5.read_bytes()) // 32, 576)
                multi.restore()
                self.assertEqual(lc1.read_bytes(), original)
                self.assertFalse(lc5.exists())


if __name__ == '__main__':
    unittest.main()
