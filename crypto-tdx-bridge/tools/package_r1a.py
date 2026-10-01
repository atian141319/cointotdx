"""New R1A package with Windows and network-isolated Linux fresh-unpack receipts."""
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import bridge as b

ROOT=Path(__file__).resolve().parents[1]


def hashes(root):
    return {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


def main():
    legacy_paths=[ROOT/'review-package.zip',ROOT/'artifacts'/'CRYPTO-TDX-R1-20261001T024633868114Z'/'review-package-r1.zip']
    legacy_before={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in legacy_paths}
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    artifact=ROOT/'artifacts'/('CRYPTO-TDX-R1A-'+stamp)
    artifact.mkdir(parents=True,exist_ok=False)
    env={**os.environ,'PYTHONUTF8':'1','PYTHONDONTWRITEBYTECODE':'1'}
    tests=subprocess.run([sys.executable,'-B','-m','unittest','discover','-s','tests','-v'],cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8')
    (artifact/'tests.txt').write_text(tests.stdout+'\n'+tests.stderr,encoding='utf-8')
    if tests.returncode: raise RuntimeError('Tests failed; no review package created')
    package_root=artifact/'staged'/'crypto-tdx-bridge'
    package_root.mkdir(parents=True)
    for p in ROOT.iterdir():
        if p.is_file() and p.suffix in ('.py','.md','.json','.ps1','.txt'):
            shutil.copy2(p,package_root/p.name)
    for name in ('tools','tests'):
        target=package_root/name; target.mkdir()
        for p in (ROOT/name).iterdir():
            if p.is_file() and p.suffix in ('.py','.ps1'): shutil.copy2(p,target/p.name)
    for name in ('evidence','validation'):
        shutil.copytree(ROOT/name,package_root/name,ignore=shutil.ignore_patterns('__pycache__','*.sqlite3','desktop.png'))
    docs=package_root/'docs'; docs.mkdir()
    for p in (ROOT.parent/'docs').glob('*.jpg'): shutil.copy2(p,docs/p.name)
    shutil.copy2(ROOT.parent/'AGENTS.md',package_root/'AGENTS.md')
    (package_root/'evidence'/'r1a').mkdir(parents=True,exist_ok=True)
    shutil.copy2(artifact/'tests.txt',package_root/'evidence'/'r1a'/'tests.txt')
    c=b.config(ROOT/'config.smoke.json')
    with b.Instance(c['data_dir']):
        # Refresh export only from existing data; no check/sync or network here.
        b.publish(c)
        snapshot=package_root/'evidence'/'r1a'/'market-snapshot.sqlite3'
        db_path=Path(c['data_dir'])/'market.sqlite3'
        if not db_path.is_file(): raise FileNotFoundError(db_path)
        source=sqlite3.connect(db_path.as_uri()+'?mode=ro',uri=True)
        destination=sqlite3.connect(snapshot)
        try:
            source.backup(destination)
            destination.execute('PRAGMA journal_mode=DELETE')
        finally: destination.close(); source.close()
        raw_target=package_root/'data'/'raw'; raw_target.parent.mkdir()
        shutil.copytree(Path(c['data_dir'])/'raw',raw_target)
        log=Path(c['data_dir'])/'bridge.log'
        if log.exists(): shutil.copy2(log,package_root/'data'/'bridge.log')
        out=Path(c['output_dir']); pointer=out/'CURRENT.json'
        batch=json.loads(pointer.read_text(encoding='utf-8'))['batch']
        export_target=package_root/'output-audit'; export_target.mkdir()
        shutil.copy2(pointer,export_target/'CURRENT.json')
        shutil.copytree(out/batch,export_target/batch)
    files=[]
    for p in sorted(package_root.rglob('*')):
        if p.is_file(): files.append({'path':p.relative_to(package_root).as_posix(),'size':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
    source_files=[x for x in files if x['path'].endswith(('.py','.ps1'))]
    version=hashlib.sha256(json.dumps(source_files,sort_keys=True).encode()).hexdigest()
    manifest={'review_status':'READY_FOR_GPT_R1A_REVIEW','overall_status':'PARTIAL','terminal_minutes':'BLOCKED','terminal_verified':False,
              'created_utc':datetime.now(timezone.utc).isoformat(),'source_version_sha256':version,
              'offline_inputs':{'db':'evidence/r1a/market-snapshot.sqlite3','raw_dir':'data/raw','export_dir':'output-audit'},
              'files':files}
    (package_root/'PACKAGE-MANIFEST.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    archive=artifact/'review-package-r1a.zip'
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as package:
        for p in sorted(package_root.rglob('*')):
            if p.is_file(): package.write(p,'crypto-tdx-bridge/'+p.relative_to(package_root).as_posix())
    archive_hash=hashlib.sha256(archive.read_bytes()).hexdigest()
    (artifact/'review-package-r1a.sha256').write_text(archive_hash+'  review-package-r1a.zip\n',encoding='ascii')
    # Fresh, independent extraction. Nothing is copied manually into this tree.
    extracted=artifact/'fresh-unpack'; extracted.mkdir()
    with zipfile.ZipFile(archive) as package: package.extractall(extracted)
    fresh=extracted/'crypto-tdx-bridge'; before=hashes(fresh)
    receipt=artifact/'offline-receipt'
    run=subprocess.run([sys.executable,'-B',str(fresh/'tools'/'offline_review.py'),'--package-dir',str(fresh),'--report-dir',str(receipt)],cwd=fresh,env=env,capture_output=True,text=True,encoding='utf-8')
    (artifact/'offline-run.txt').write_text(run.stdout+'\n'+run.stderr,encoding='utf-8')
    if run.returncode: raise RuntimeError('Fresh-unpack offline verification failed: '+run.stdout+run.stderr)
    if before!=hashes(fresh): raise ValueError('Unpacked inputs changed')
    report=receipt/'offline-verification.json'
    receipt_hash=hashlib.sha256(report.read_bytes()).hexdigest()
    (artifact/'offline-receipt.sha256').write_text(receipt_hash+'  offline-receipt/offline-verification.json\n',encoding='ascii')
    def linux_path(path):
        resolved=path.resolve()
        return '/mnt/'+resolved.drive[0].lower()+resolved.as_posix()[2:]
    linux_dir=artifact/'linux-receipt'
    linux=subprocess.run(['wsl','-d','Ubuntu','-u','root','--','unshare','--net','python3','-B',
                          linux_path(ROOT/'tools'/'linux_fresh_review.py'),'--archive',linux_path(archive),
                          '--report-dir',linux_path(linux_dir)],env=env,capture_output=True,text=True,encoding='utf-8')
    (artifact/'linux-run.txt').write_text(linux.stdout+'\n'+linux.stderr,encoding='utf-8')
    if linux.returncode: raise RuntimeError('Linux fresh-unpack tests/review failed: '+linux.stdout+linux.stderr)
    linux_receipt=linux_dir/'linux-receipt.json'
    linux_hash=hashlib.sha256(linux_receipt.read_bytes()).hexdigest()
    linux_evidence=[]
    for file in sorted(linux_dir.iterdir()):
        if file.is_file(): linux_evidence.append(hashlib.sha256(file.read_bytes()).hexdigest()+'  '+file.relative_to(artifact).as_posix())
    (artifact/'linux-receipt.sha256').write_text('\n'.join(linux_evidence)+'\n',encoding='ascii')
    legacy_after={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in legacy_paths}
    if legacy_before!=legacy_after: raise ValueError('Legacy packages changed')
    delivery={'review_status':'READY_FOR_GPT_R1A_REVIEW','overall_status':'PARTIAL','terminal_minutes':'BLOCKED',
              'artifact_directory':str(artifact),'archive':str(archive),'archive_sha256':archive_hash,
              'source_version_sha256':version,'offline_receipt':str(report),'receipt_sha256':receipt_hash,
              'fresh_unpacked_input_unchanged':True,'files':len(files),
              'linux_receipt':str(linux_receipt),'linux_receipt_sha256':linux_hash,
              'linux_fresh_unpack_tests_and_verifier_passed':True,'legacy_packages_sha256':legacy_after}
    (artifact/'delivery.json').write_text(json.dumps(delivery,indent=2),encoding='utf-8')
    print(json.dumps(delivery,indent=2))


if __name__=='__main__': main()
