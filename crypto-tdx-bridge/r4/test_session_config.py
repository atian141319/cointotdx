import json
from pathlib import Path
import struct
import tempfile
import unittest

from session_config import apply, converted, locate, restore, NATIVE_10, CONTINUOUS_05


def record(market=10, values=NATIVE_10):
    return bytes([market]) + b'?' * 8 + b'\0' + struct.pack('<10H', *values) + struct.pack('<I', 1)


class SessionTests(unittest.TestCase):
    def test_find_relocated_record_and_preserve_other_markets(self):
        for count in (0, 1, 40):
            source = record(16) * count + record() + record(11)
            new, offset = converted(source, NATIVE_10)
            self.assertEqual(offset, count * 34)
            self.assertEqual(locate(new)[1], CONTINUOUS_05)
            self.assertEqual(new[:offset], source[:offset])
            self.assertEqual(new[offset + 34:], source[offset + 34:])

    def test_fail_closed_on_identity_tail_alignment_or_original_mismatch(self):
        for data in (record(16), record() * 2, record() + b'x', record()[:-4] + b'abcd'):
            with self.assertRaises(ValueError):
                converted(data, NATIVE_10)
        with self.assertRaises(ValueError):
            converted(record(values=CONTINUOUS_05), NATIVE_10)

    def test_backup_restore_and_running_or_concurrent_change_protection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'session.dat'
            source = record(16) + record()
            target.write_bytes(source)
            with self.assertRaises(RuntimeError):
                apply(target, root/'backups', NATIVE_10, client_running=True)
            self.assertEqual(target.read_bytes(), source)
            receipt = apply(target, root/'backups', NATIVE_10, client_running=False)
            self.assertEqual(locate(target.read_bytes())[1], CONTINUOUS_05)
            modified = target.read_bytes()
            target.write_bytes(modified + b'x')
            with self.assertRaises(ValueError):
                restore(receipt, client_running=False)
            target.write_bytes(modified)
            restore(receipt, client_running=False)
            self.assertEqual(target.read_bytes(), source)


if __name__ == '__main__':
    unittest.main()
