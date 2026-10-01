"""Standard Windows edit/combo/button operations, isolated process only."""
import argparse
import ctypes as C
from ctypes import wintypes as W
import json
from pathlib import Path
import subprocess

p = argparse.ArgumentParser()
p.add_argument('handle', type=int)
p.add_argument('action', choices=['inspect', 'text', 'select', 'button'])
p.add_argument('value', nargs='?', default='')
a = p.parse_args()
u = C.WinDLL('user32', use_last_error=True)
u.SendMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
u.SendMessageW.restype = C.c_ssize_t
owner = W.DWORD()
u.GetWindowThreadProcessId(W.HWND(a.handle), C.byref(owner))
command = f"(Get-CimInstance Win32_Process -Filter 'ProcessId={owner.value}').ExecutablePath"
actual = subprocess.check_output(['powershell', '-NoProfile', '-Command', command], text=True).strip()
expected = str(Path(__file__).resolve().parents[1] / 'client' / 'tdxw.exe')
if actual.lower() != expected.lower():
    raise RuntimeError('Control does not belong to isolated client')
buffer = C.create_unicode_buffer(512)
u.GetClassNameW(W.HWND(a.handle), buffer, 512)
kind = buffer.value
def send(message, value=0, pointer=0):
    return u.SendMessageW(a.handle, message, value, pointer)
items = []
if kind.lower() == 'combobox':
    for i in range(send(0x146)):
        value = C.create_unicode_buffer(send(0x149, i) + 1)
        send(0x148, i, C.addressof(value))
        items.append(value.value)
if a.action == 'text':
    if kind.lower() != 'edit':
        raise RuntimeError('Not an edit control')
    value = C.create_unicode_buffer(a.value)
    send(0x000C, 0, C.addressof(value))
elif a.action == 'select':
    if a.value.startswith('#'):
        a.value = items[int(a.value[1:])]
    if a.value not in items:
        raise RuntimeError(f'Exact item absent: {items}')
    send(0x14E, items.index(a.value))
    parent = u.GetParent(W.HWND(a.handle))
    control_id = u.GetDlgCtrlID(W.HWND(a.handle))
    u.SendMessageW(parent, 0x111, control_id | (1 << 16), a.handle)
elif a.action == 'button':
    if kind.lower() != 'button':
        raise RuntimeError('Not a button control')
    send(0xF5)
text = C.create_unicode_buffer(4096)
send(0xD, len(text), C.addressof(text))
print(json.dumps({'handle': a.handle, 'class': kind, 'action': a.action,
                  'value': text.value, 'items': items}, ensure_ascii=False))
