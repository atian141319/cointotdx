"""Freeze the working UTC display trial and create a separate head diagnostic."""
import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
from pathlib import Path
import shutil
import time
from client_control import Client

base = Path(__file__).resolve().parent
previous = base/'acceptance-20261002-2355'
root = base/'acceptance-20261002-head'
if root.exists():
    raise RuntimeError('Head workbench already exists; never replace prior evidence')
config = json.loads((previous/'settings.json').read_text(encoding='utf-8'))
client = Client(config)
ids = {w[2] for w in client.windows()}
client.kernel.OpenProcess.argtypes = [W.DWORD,W.BOOL,W.DWORD]
client.kernel.WaitForSingleObject.argtypes = [W.HANDLE,W.DWORD]
handles = [client.kernel.OpenProcess(0x100000,False,pid) for pid in ids]
for handle,title,pid in client.windows():
    if 'V7.73' in title:
        client.user.PostMessageW(W.HWND(handle),0x10,0,0)
time.sleep(.5)
for handle,_,_ in client.windows():
    for item in client.children(handle):
        if item['class']=='Button' and item['name']=='\u9000\u51fa':
            client.user.PostMessageW(W.HWND(handle),0x111,item['id'],item['handle'])
for handle in handles:
    if not handle:
        raise RuntimeError('Could not obtain process exit handle')
    result = client.kernel.WaitForSingleObject(handle,20000)
    client.kernel.CloseHandle(handle)
    if result != 0:
        raise RuntimeError('Client did not exit; freeze cancelled')
if client.windows():
    raise RuntimeError('Client still visible; freeze cancelled')
root.mkdir()
shutil.copytree(previous/'trial-client',root/'successful-client')
shutil.copytree(root/'successful-client',root/'trial-client')
files = [{'path':p.relative_to(root/'successful-client').as_posix(),'bytes':p.stat().st_size,
          'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
         for p in sorted((root/'successful-client').rglob('*')) if p.is_file()]
(root/'SUCCESS-FREEZE.json').write_text(json.dumps({'files':files,'UTC_offset':0,
    'LC5_label':'source UTC open + 4 minutes','session':'continuous-05 trial',
    'source':str(previous/'trial-client')},indent=2),encoding='utf-8')
for file in ('open_code.py','read_boundary.py','select_observed.py','enter_offline.py'):
    shutil.copy2(previous/file,root/file)
shutil.copy2(previous/'market.sqlite3',root/'market.sqlite3')
shutil.copy2(base/'acceptance-20261001-review/period-restart/frozen/market.sqlite3',root/'btc-reference.sqlite3')
config['tdx'] = {'installation':str(root/'trial-client'),
    'executable':str(root/'trial-client/tdxw.exe'),'data_directory':str(root/'trial-client/vipdoc')}
config['data_directory'] = str(root/'no-collector')
(root/'settings.json').write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
print('Frozen working client; new diagnostic:',root)
