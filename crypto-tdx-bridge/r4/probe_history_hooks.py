import json
from pathlib import Path
import subprocess
import sys
import time
from client_control import Client
from history_guard import HistoryGuard
from settings import load

root = Path(sys.argv[1]).resolve(strict=True)
client = Client(load(root / 'settings.json'))
guard = HistoryGuard()
main, title, pid = next(w for w in client.windows() if 'V7.73' in w[1])
guard.watch(client, main, pid)
try:
    command = [sys.executable, str(Path(__file__).with_name('trial_chart_probe.py')), str(root), 'latest']
    child = subprocess.Popen(command)
    child.wait(timeout=10)
    time.sleep(1)
    print(json.dumps({'notifications': guard.monitor.navigation_notifications,
        'error': guard.monitor.error, 'alive': guard.monitor.is_alive(),
        'resume_requested': guard.resume_requested}))
finally:
    guard.close()
