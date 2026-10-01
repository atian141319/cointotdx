import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('daily_txt', Path(__file__).with_name('daily_txt.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class DailyTests(unittest.TestCase):
    def row(self):
        return ('BTCUSDT', 1790380800000, 1790467199999,
                json.dumps([1790380800000, '1.01000000', '2', '1', '1.5',
                            '0.00123456', 1790467199999, '987654321.12345678',
                            0, '0', '0', '0']), 'raw-reference')

    def test_explicit_mapping_and_exact_fraction(self):
        line, source = module.convert(self.row())
        self.assertEqual(line.split('\t'), ['2026-09-26', '1.01000000', '2',
            '1', '1.5', '0.00123456', '987654321.12345678'])
        self.assertEqual(source['raw_id'], 'raw-reference')

    def test_invalid_number_and_payload_fail(self):
        for invalid in ('', 'NaN', 'bad', '-1'):
            row = list(self.row())
            payload = json.loads(row[3]); payload[5] = invalid
            row[3] = json.dumps(payload)
            with self.assertRaises((ValueError, ArithmeticError)):
                module.convert(row)
        row = list(self.row()); row[1] += 60000
        with self.assertRaises(ValueError):
            module.convert(row)

    def test_missing_database_does_not_create(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / 'absent.sqlite3'
            with self.assertRaises(FileNotFoundError):
                module.export(missing, Path(directory) / 'out')
            self.assertFalse(missing.exists())


if __name__ == '__main__':
    unittest.main()
