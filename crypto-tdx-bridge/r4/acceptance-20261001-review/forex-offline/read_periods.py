import json
from pathlib import Path
import sys
import time
from ctypes import wintypes as W

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root.parents[1]))
from client_control import Client
client = Client(json.loads((root / "settings.json").read_text(encoding="utf-8")))

def key(view, value):
    client.user.PostMessageW(W.HWND(view), 0x100, value, 0)
    client.user.PostMessageW(W.HWND(view), 0x101, value, 0)

def values():
    return {str(item["id"]): item["name"] for window in client.windows()
            for item in client.children(window[0])
            if item["class"] == "Static" and 1354 <= item["id"] <= 1361}

results = {}
identity = sys.argv[1] if len(sys.argv) > 1 else "10#R4BTC1"
prefix = "comex" if identity == "16#R4BTC2" else "forex"
for period in ("15m", "30m", "1h"):
    client.period(period)
    time.sleep(1.5)
    view = next(item["handle"] for window in client.windows()
                for item in client.children(window[0])
                if item["class"].endswith(":300b"))
    key(view, 0x23)
    for _ in range(180):
        key(view, 0x27)
    time.sleep(1)
    key(view, 0x25)
    time.sleep(0.3)
    key(view, 0x27)
    time.sleep(0.3)
    rows = []
    for _ in range(32):
        rows.append(values())
        key(view, 0x25)
        time.sleep(0.3)
    results[period] = {"identity": identity, "rows_newest_first": rows,
                       "comparison_scope": "Same frozen, lossy BTC display records; not actual FX quotes"}
    client.capture(root / (prefix + "-diagnostic-" + period + ".bmp"))
    (root / (prefix + "-period-values.json")).write_text(json.dumps(results, ensure_ascii=False,
        indent=2), encoding="utf-8")
    print(period, rows[0].get("1354"), rows[0].get("1356"), flush=True)
