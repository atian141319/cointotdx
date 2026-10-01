"""Focused regression: a moved client remains editable, but cannot publish."""
import json
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from desktop import Desktop
from settings import default_settings, load


class PathRecoveryTests(unittest.TestCase):
    def configuration(self, directory):
        value = default_settings()
        client = directory / 'removed-client'
        value['tdx'] = {'installation': str(client), 'executable': str(client / 'tdxw.exe'),
                        'data_directory': str(client / 'vipdoc')}
        value['data_directory'] = str(directory / 'exact')
        path = directory / 'settings.json'
        path.write_text(json.dumps(value), encoding='utf-8')
        return path, value

    def test_strict_load_still_rejects_missing_executable(self):
        with tempfile.TemporaryDirectory() as temp:
            path, value = self.configuration(Path(temp))
            with self.assertRaisesRegex(ValueError, 'executable missing'):
                load(path)
            self.assertEqual(load(path, check_paths=False), value)

    def test_window_opens_preserves_config_and_blocks_sync(self):
        with tempfile.TemporaryDirectory() as temp:
            path, value = self.configuration(Path(temp))
            before = path.read_bytes()
            root = tk.Tk()
            root.withdraw()
            try:
                ui = Desktop(root, path)
                self.assertIn('executable missing', ui.startup_path_error)
                self.assertEqual(ui.vars['executable'].get(), value['tdx']['executable'])
                with patch('desktop.messagebox.showerror'), patch('desktop.Engine') as engine:
                    ui.start()
                    engine.assert_not_called()
                self.assertEqual(path.read_bytes(), before)
                self.assertIsNone(ui.engine)
            finally:
                root.destroy()

    def test_corrected_paths_save_and_reopen(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            path, _ = self.configuration(directory)
            client = directory / 'selected-client'
            client.mkdir()
            (client / 'vipdoc').mkdir()
            (client / 'tdxw.exe').write_bytes(b'MZ')  # Existence check only; never executed.
            root = tk.Tk()
            root.withdraw()
            try:
                ui = Desktop(root, path)
                for key, value in [('installation', client), ('executable', client / 'tdxw.exe'),
                                   ('tdx_data', client / 'vipdoc')]:
                    ui.vars[key].set(str(value))
                self.assertTrue(ui.save())
            finally:
                root.destroy()
            reopened = load(path)
            self.assertEqual(reopened['tdx']['executable'], str(client / 'tdxw.exe'))


if __name__ == '__main__':
    unittest.main()
