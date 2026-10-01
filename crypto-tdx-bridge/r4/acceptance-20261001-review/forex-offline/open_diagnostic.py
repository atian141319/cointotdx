import ctypes as C
from ctypes import wintypes as W
import json
from pathlib import Path
import sys
import time

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root.parents[1]))
from client_control import Client
client = Client(json.loads((root / "settings.json").read_text(encoding="utf-8")))
u, k = client.user, client.kernel
u.GetForegroundWindow.restype = W.HWND
u.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
u.SetForegroundWindow.argtypes = [W.HWND]
u.SetFocus.argtypes = [W.HWND]
main = next(w[0] for w in client.windows() if "V7.73" in w[1])
foreground = u.GetForegroundWindow()
foreground_thread = u.GetWindowThreadProcessId(foreground, None)
own_thread = k.GetCurrentThreadId()
target_thread = u.GetWindowThreadProcessId(W.HWND(main), None)
u.AttachThreadInput(own_thread, foreground_thread, True)
u.AttachThreadInput(own_thread, target_thread, True)
try:
    u.SetForegroundWindow(W.HWND(main))
    view = next((i["handle"] for i in client.children(main)
                 if i["class"].endswith(":300b")), main)
    u.SetFocus(W.HWND(view))
    if u.GetForegroundWindow() != main:
        raise RuntimeError("Foreground guard failed; no input sent")
    class Keyboard(C.Structure):
        _fields_ = [("vk", W.WORD), ("scan", W.WORD), ("flags", W.DWORD),
                    ("time", W.DWORD), ("extra", C.c_size_t)]
    class Mouse(C.Structure):
        _fields_ = [("dx", W.LONG), ("dy", W.LONG), ("data", W.DWORD),
                    ("flags", W.DWORD), ("time", W.DWORD), ("extra", C.c_size_t)]
    class Payload(C.Union):
        _fields_ = [("keyboard", Keyboard), ("mouse", Mouse)]
    class Input(C.Structure):
        _fields_ = [("kind", W.DWORD), ("payload", Payload)]
    u.SendInput.argtypes = [W.UINT, C.POINTER(Input), C.c_int]
    code = sys.argv[1] if len(sys.argv) > 1 else "R4BTC1"
    if code not in ("R4BTC1", "R4BTC2", "397901", "EURUSD"):
        raise ValueError("Only explicitly prepared diagnostic/control identities")
    for character in code:
        for flags in (4, 6):
            event = Input(kind=1, payload=Payload(keyboard=Keyboard(
                scan=ord(character), flags=flags)))
            if u.SendInput(1, C.byref(event), C.sizeof(event)) != 1:
                raise RuntimeError("Keyboard input failed")
    time.sleep(1)
    for flags in (0, 2):
        event = Input(kind=1, payload=Payload(keyboard=Keyboard(vk=13, flags=flags)))
        u.SendInput(1, C.byref(event), C.sizeof(event))
    time.sleep(2)
    client.capture(root / ("lookup-" + code + ".bmp"))
    (root / ("lookup-" + code + ".json")).write_text(json.dumps(
        {"requested": code, "windows": client.windows(),
         "named_controls": [i for w in client.windows()
                            for i in client.children(w[0]) if i["name"]]},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(client.windows(), ensure_ascii=True))
finally:
    u.AttachThreadInput(own_thread, target_thread, False)
    u.AttachThreadInput(own_thread, foreground_thread, False)
