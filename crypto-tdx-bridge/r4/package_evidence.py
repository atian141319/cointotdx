"""Create a new immutable R4 evidence snapshot without touching signed packages."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import time


def main():
    project = Path(__file__).resolve().parent.parent
    home = project / 'r4'
    config = json.loads((home / 'live-settings.json').read_text())
    data = Path(config['data_directory'])
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    root = project / 'artifacts' / ('CRYPTO-TDX-R4-' + stamp)
    root.mkdir(parents=True, exist_ok=False)
    snapshot = root / 'snapshot'
    snapshot.mkdir()
    with sqlite3.connect((data / 'market.sqlite3').as_uri() + '?mode=ro', uri=True) as source:
        with sqlite3.connect(snapshot / 'market.sqlite3') as target:
            source.backup(target)
    shutil.copytree(data / 'raw', snapshot / 'raw')
    shutil.copytree(data / 'display', snapshot / 'publication')
    shutil.copy2(data / 'runtime.log', snapshot / 'runtime.log')
    output = snapshot / 'display'
    output.mkdir()
    for relative in ('sz/minline/sz397901.lc1', 'sz/fzline/sz397901.lc5', 'sz/lday/sz397901.day'):
        path = Path(config['tdx']['data_directory']) / relative
        shutil.copy2(path, output / path.name)
    shutil.copytree(home / 'evidence', root / 'evidence')
    client = Path(config['tdx']['installation'])
    shutil.copy2(client / 'T0002/lc/lcext.lei', root / 'evidence/lcext.lei')
    executable = Path(config['tdx']['executable'])
    original = Path('D:/Programs/tdx/tdxw.exe')
    client_evidence = {'selected_executable':str(executable), 'selected_sha256':hashlib.sha256(executable.read_bytes()).hexdigest(),
        'registry_source':str(client / 'T0002/lc/lcext.lei'), 'registry_record_bytes':320,
        'managed_code':'397901','display_name':'BTCUSDT','market':'sz'}
    if original.is_file():
        client_evidence['original_executable_sha256'] = hashlib.sha256(original.read_bytes()).hexdigest()
        client_evidence['binaries_identical'] = client_evidence['original_executable_sha256'] == client_evidence['selected_sha256']
    (root / 'evidence/client-identity.json').write_text(json.dumps(client_evidence,indent=2),encoding='utf-8')
    shutil.copytree(home / 'release', root / 'windows')
    code = root / 'source'
    code.mkdir()
    for path in home.iterdir():
        if path.is_file() and path.suffix in ('.py','.ps1','.txt','.md','.json','.spec'):
            shutil.copy2(path, code / path.name)
    for name in ('bridge.py', 'rate_control.py'):
        shutil.copy2(project / name, code / name)
    signed = json.loads((project / 'experiments/r3-lc1-user-test/evidence/signed-version-preservation.json').read_text())
    unchanged = []
    for entry in signed['signed_source_files']:
        digest = hashlib.sha256((project / entry['path']).read_bytes()).hexdigest()
        unchanged.append(dict(entry,actual_sha256=digest,unchanged=digest==entry['sha256']))
    if not all(x['unchanged'] for x in unchanged):
        raise ValueError('Signed source changed')
    archive = project / 'artifacts/CRYPTO-TDX-R1A-20261001T034113542138Z/review-package-r1a.zip'
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != signed['signed_archive_sha256']:
        raise ValueError('Signed archive changed')
    (root / 'preservation.json').write_text(json.dumps({'signed_archive_sha256':digest,'signed_source_files':unchanged},indent=2),encoding='utf-8')
    files = [{'path':path.relative_to(root).as_posix(),'size':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
             for path in sorted(root.rglob('*')) if path.is_file()]
    source_files = [item for item in files if item['path'].startswith('source/')]
    version = hashlib.sha256(json.dumps(source_files,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    (root / 'manifest.json').write_text(json.dumps({'schema':1,'observed_ms':int(time.time()*1000),'source_version':version,'files':files},indent=2),encoding='utf-8')
    print(root)


if __name__ == '__main__': main()
