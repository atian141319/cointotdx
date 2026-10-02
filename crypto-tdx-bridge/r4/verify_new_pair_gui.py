"""Actual Tk add/save/reopen and isolated registration, with no live config edits."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tkinter as tk
from tkinter import messagebox, ttk

from desktop import Desktop
from external_registry import register
from settings import load, registration_check


trial = Path(sys.argv[1]).resolve(strict=True)
config_path = trial / 'settings.json'
messagebox.showerror = lambda title, text, **kwargs: (_ for _ in ()).throw(AssertionError(text))
window = tk.Tk()
window.withdraw()
desktop = Desktop(window, config_path)
desktop.edit_pair()
dialog = next(child for child in window.winfo_children() if isinstance(child, tk.Toplevel))
values = {0: 'ADAUSDT', 1: 'ADAUSDT试验', 3: '2026-10-02T00:00:00Z'}
entries = [child for child in dialog.winfo_children() if isinstance(child, ttk.Entry)]
assert len(entries) == 4, 'No low-level label/market/context fields should require manual input'
for entry in entries:
    row = int(entry.grid_info()['row'])
    if row in values:
        entry.delete(0, 'end')
        entry.insert(0, values[row])
button = next(child for child in dialog.winfo_children() if isinstance(child, ttk.Button) and child.cget('text') == '保存')
button.invoke()
assert desktop.save()
window.destroy()
window = tk.Tk()
window.withdraw()
desktop = Desktop(window, config_path)
pair = desktop.config['pairs'][0]
assert pair['symbol'] == 'ADAUSDT' and pair['lc5_time_label'] == 'last_minute'
assert pair['display_context_start'] == '2026-10-01T23:00:00+00:00'
assert pair['market'] == 'ds' and pair['market_id'] == 10
window.destroy()
config = load(config_path)
registry = Path(config['tdx']['installation']) / 'T0002/hq_cache/ds_stk.dat'
before = registry.read_bytes()
owners = register(config, [pair])
allowed, reason = registration_check(config, pair)
assert allowed
assert registry.read_bytes().startswith(before)
(trial / 'NEW-PAIR-GUI-RECEIPT.json').write_text(json.dumps({
    'observed_UTC': datetime.now(timezone.utc).isoformat(), 'new_pair': pair,
    'actual_add_dialog_saved': True, 'window_reopened_config_retained': True,
    'low_level_parameters_entered': False, 'registration_verified': allowed,
    'registration_reason': reason, 'registry_original_prefix_unchanged': True,
    'registry_before_sha256': hashlib.sha256(before).hexdigest(),
    'registry_after_sha256': hashlib.sha256(registry.read_bytes()).hexdigest(),
    'live_config_changed': False, 'chart_display_verified': False,
    'scope': 'source GUI and actual isolated catalogue; online/chart checked separately'},
    ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(pair, ensure_ascii=True))
