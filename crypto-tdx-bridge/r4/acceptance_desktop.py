"""Local acceptance driver: invoke actual desktop widgets, no mocks or network server."""
import argparse
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from desktop import Desktop


def widgets(parent):
    for child in parent.winfo_children():
        yield child
        yield from widgets(child)


def button(parent, text):
    matches = [widget for widget in widgets(parent)
               if isinstance(widget, ttk.Button) and widget.cget('text') == text]
    if len(matches) != 1:
        raise RuntimeError(f'Expected one public button {text}; found {len(matches)}')
    return matches[0]


def sanitized(value):
    value = copy.deepcopy(value)
    if 'proxy' in value:
        value['proxy'] = ''
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--control', type=Path, required=True)
    args = parser.parse_args()
    args.control.mkdir(parents=True, exist_ok=True)
    root = tk.Tk()
    ui = Desktop(root, args.config)
    events = []

    def execute(command):
        action = command['action']
        if action == 'fields':
            for key, value in command['values'].items():
                ui.vars[key].set(value)
        elif action == 'add_pair':
            ui.notebook.select(1)
            button(root, '添加').invoke()
            dialog = next(widget for widget in root.winfo_children() if isinstance(widget, tk.Toplevel))
            entries = [widget for widget in dialog.winfo_children() if isinstance(widget, ttk.Entry)]
            values = command['pair']
            for widget, key in zip(entries, ('symbol', 'display_name', 'code', 'market', 'history_start')):
                widget.delete(0, 'end')
                widget.insert(0, values[key])
            button(dialog, '保存').invoke()
        elif action == 'select_pair':
            ui.notebook.select(1)
            index = next(i for i, pair in enumerate(ui.config['pairs']) if pair['symbol'] == command['symbol'])
            ui.tree.selection_set(str(index))
        elif action == 'invoke':
            button(root, command['button']).invoke()
        elif action == 'close':
            ui.close()
        else:
            raise ValueError('Unsupported acceptance action')

    def poll():
        for request in sorted(args.control.glob('request-*.json')):
            result_path = request.with_name(request.name.replace('request-', 'result-'))
            if result_path.exists():
                continue
            command = json.loads(request.read_text(encoding='utf-8'))
            result = {'utc': datetime.now(timezone.utc).isoformat(), 'action': command['action']}
            try:
                execute(command)
                result['executed'] = True
            except Exception as error:
                result['executed'] = False
                result['error'] = str(error)
            result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            events.append(result)
            if command['action'] == 'close':
                return
        state = {'observed_utc': datetime.now(timezone.utc).isoformat(), 'process_id':os.getpid(),
                 'configuration': sanitized(ui.config),
                 'visible_fields': {key: '' if key == 'proxy' else var.get() for key, var in ui.vars.items()},
                 'engine': ui.engine.snapshot() if ui.engine else None,
                 'messages': ui.status_text.get('1.0', 'end'), 'events': events}
        temporary = args.control / 'state.tmp'
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
        try:
            temporary.replace(args.control / 'state.json')
        except PermissionError:
            # Concurrent readers on Windows may temporarily deny deletion; keep polling.
            pass
        root.after(300, poll)

    root.after(500, poll)
    root.mainloop()


if __name__ == '__main__':
    main()
