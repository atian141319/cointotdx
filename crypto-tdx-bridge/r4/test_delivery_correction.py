"""Delivery integrity regressions, without market/network/historical tests."""
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from contextlib import closing

from delivery_integrity import audit_local_imports, file_inventory, verify_manifest


class DeliveryCorrectionTests(unittest.TestCase):
    def test_missing_local_dependency_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'bridge.py').write_text('import rate_control\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Missing local imports'):
                audit_local_imports(root)
            (root / 'rate_control.py').write_text('', encoding='utf-8')
            self.assertEqual(audit_local_imports(root)['missing'], [])

    def test_extra_file_and_mutated_file_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data = root / 'input.txt'
            data.write_text('frozen', encoding='utf-8')
            before = file_inventory(root)
            manifest = {'files':[{'path':name, **item} for name,item in before.items()]}
            (root / 'MANIFEST.json').write_text(json.dumps(manifest), encoding='utf-8')
            inventory = file_inventory(root)
            verify_manifest(root, inventory)
            extra = root / 'unexpected.txt'
            extra.write_text('added', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Manifest mismatch'):
                verify_manifest(root, file_inventory(root))
            extra.unlink()
            data.write_text('changed', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Manifest mismatch'):
                verify_manifest(root, file_inventory(root))

    def test_sqlite_sidecars_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for suffix in ('-wal', '-shm', '-journal'):
                path = root / ('snapshot.sqlite3' + suffix)
                path.write_bytes(b'')
                with self.assertRaisesRegex(ValueError, 'SQLite sidecar'):
                    file_inventory(root)
                path.unlink()

    def test_immutable_complete_snapshot_creates_no_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / 'snapshot.sqlite3'
            with closing(sqlite3.connect(path)) as db:
                db.execute('CREATE TABLE evidence(value TEXT)')
                db.execute('INSERT INTO evidence VALUES(?)', ('precise',))
                db.commit()
            before = file_inventory(root)
            with closing(sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
                self.assertEqual(db.execute('SELECT value FROM evidence').fetchone()[0], 'precise')
                with self.assertRaises(sqlite3.OperationalError):
                    db.execute('INSERT INTO evidence VALUES("forbidden")')
            self.assertEqual(file_inventory(root), before)

    def test_unsafe_manifest_paths_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ('../outside', '/absolute', 'C:/absolute', 'a\\b'):
                (root / 'MANIFEST.json').write_text(json.dumps({'files':[
                    {'path':name,'bytes':0,'sha256':hashlib.sha256(b'').hexdigest()}]}), encoding='utf-8')
                with self.assertRaises(ValueError):
                    verify_manifest(root, file_inventory(root))


if __name__ == '__main__':
    unittest.main()
