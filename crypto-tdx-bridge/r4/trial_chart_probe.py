"""Public UI probes restricted to the independent completion client."""
import ctypes as C
from ctypes import wintypes as W
import json
from pathlib import Path
import sys
import time

from client_control import Client
from settings import load

trial = Path(sys.argv[1]).resolve(strict=True)
client = Client(load(trial / 'settings.json'))
if Path(client.config['tdx']['installation']).parent != trial:
    raise ValueError('Probe requires this independent trial client')
action = sys.argv[2]
user = client.user
user.GetForegroundWindow.restype = W.HWND
main = next(w[0] for w in client.windows() if 'V7.73' in w[1])
view = next((i['handle'] for i in client.children(main) if i['class'].endswith(':300b')), main)
own = client.kernel.GetCurrentThreadId()
foreground_thread = user.GetWindowThreadProcessId(user.GetForegroundWindow(), None)
target_thread = user.GetWindowThreadProcessId(W.HWND(main), None)
user.AttachThreadInput(own, foreground_thread, True)
user.AttachThreadInput(own, target_thread, True)


def key(value):
    pid = W.DWORD()
    user.GetWindowThreadProcessId(user.GetForegroundWindow(), C.byref(pid))
    expected = next(w[2] for w in client.windows() if w[0] == main)
    if pid.value != expected:
        raise RuntimeError('Foreground changed; no input')
    user.keybd_event(value, 0, 0, 0)
    user.keybd_event(value, 0, 2, 0)


def fields():
    pid = next(w[2] for w in client.windows() if w[0] == main)
    handles = []
    @C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
    def callback(handle, argument):
        actual = W.DWORD()
        user.GetWindowThreadProcessId(handle, C.byref(actual))
        if actual.value == pid and user.IsWindowVisible(handle):
            handles.append(int(handle))
        return True
    user.EnumWindows(callback, 0)
    return {str(i['id']): i['name'] for h in handles for i in client.children(h)
            if i['class'] == 'Static' and 1354 <= i['id'] <= 1361}


try:
    user.ShowWindow(W.HWND(main), 9)
    user.SetForegroundWindow(W.HWND(main))
    user.SetFocus(W.HWND(view))
    if action == 'open':
        code = sys.argv[3]
        if code not in ('397906', 'GC00Y'):
            raise ValueError('Only newly registered trial and genuine native control')
        for character in code:
            key(ord(character))
        time.sleep(.7)
        key(13)
        time.sleep(1)
        client.capture(trial / (code + '-opened.bmp'))
        print(json.dumps(client.windows(), ensure_ascii=True))
    elif action == 'read':
        period, name = sys.argv[3:5]
        client.period(period)
        time.sleep(.6)
        view = next((i['handle'] for i in client.children(main) if i['class'].endswith(':300b')), main)
        user.SetForegroundWindow(W.HWND(main))
        user.SetFocus(W.HWND(view))
        key(0x23)
        for _ in range(100):
            key(0x27)
        time.sleep(.3)
        rows = []
        count = int(sys.argv[5]) if len(sys.argv) > 5 else 20
        for _ in range(count):
            value = fields()
            value['_observed_ms'] = int(time.time() * 1000)
            rows.append(value)
            key(0x25)
            time.sleep(.15)
        (trial / (name + '.json')).write_text(json.dumps({'windows': client.windows(),
            'rows': rows, 'period_requested': period, 'source': 'public native Static controls'},
            ensure_ascii=False, indent=2), encoding='utf-8')
        client.capture(trial / (name + '-chart.bmp'))
        print(json.dumps(rows[:2], ensure_ascii=True))
    elif action == 'latest':
        key(0x23)
        key(0x1B)
    else:
        raise ValueError('Unknown operation')
finally:
    user.AttachThreadInput(own, target_thread, False)
    user.AttachThreadInput(own, foreground_thread, False)
