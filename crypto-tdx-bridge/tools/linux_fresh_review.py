"""Run inside a Linux network namespace: extract ZIP anew, test and verify unchanged inputs."""
import argparse
import hashlib
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

sys.dont_write_bytecode=True


def hashes(root):
    return {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--report-dir',type=Path,required=True)
    args=parser.parse_args()
    if sys.platform!='linux': parser.error('Linux required')
    # WSL sysfs can retain the host namespace's device listing after unshare.
    # if_nameindex queries the process's actual network namespace.
    interfaces=socket.if_nameindex()
    if any(name!='lo' for index,name in interfaces):
        parser.error('Run under unshare --net; no external network interfaces allowed')
    report_dir=args.report_dir.resolve(); report_dir.mkdir(parents=True,exist_ok=False)
    workspace=Path(tempfile.mkdtemp(prefix='crypto-tdx-r1a-'))
    fresh=workspace/'crypto-tdx-bridge'
    with zipfile.ZipFile(args.archive) as package: package.extractall(workspace)
    before=hashes(fresh)
    env={**os.environ,'PYTHONUTF8':'1','PYTHONDONTWRITEBYTECODE':'1'}
    tests=subprocess.run([sys.executable,'-B','-m','unittest','discover','-s','tests','-v'],cwd=fresh,env=env,capture_output=True,text=True,encoding='utf-8')
    (report_dir/'tests.txt').write_text(tests.stdout+'\n'+tests.stderr,encoding='utf-8')
    review=subprocess.run([sys.executable,'-B','tools/offline_review.py','--package-dir',str(fresh),'--report-dir',str(workspace/'receipt')],cwd=fresh,env=env,capture_output=True,text=True,encoding='utf-8')
    (report_dir/'offline-run.txt').write_text(review.stdout+'\n'+review.stderr,encoding='utf-8')
    if (workspace/'receipt'/'offline-verification.json').exists():
        shutil.copy2(workspace/'receipt'/'offline-verification.json',report_dir/'offline-verification.json')
    unchanged=before==hashes(fresh)
    result={'platform':platform.platform(),'python':sys.version,'fresh_linux_unpack':str(fresh),
            'archive_sha256':hashlib.sha256(args.archive.read_bytes()).hexdigest(),
            'tests_exit_code':tests.returncode,'offline_review_exit_code':review.returncode,
            'package_unchanged':unchanged,'network_isolation':'Linux unshare --net; loopback only',
            'network_interfaces':interfaces,
            'input_files_modified':False if unchanged else True,
            'result':'VERIFIED_OFFLINE_EVIDENCE' if not tests.returncode and not review.returncode and unchanged else 'FAILED'}
    (report_dir/'linux-receipt.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))
    if result['result']=='FAILED':
        print(tests.stderr[-6000:]); print(review.stdout+review.stderr)
        return 1
    return 0


if __name__=='__main__': sys.exit(main())
