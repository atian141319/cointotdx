"""One-command fresh-unpack verification; explicitly denies Python networking."""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True


def deny_network(event, args):
    if event.startswith('socket.'):
        raise RuntimeError('OFFLINE_REVIEW_NETWORK_FORBIDDEN: '+event)


def tree_hashes(root):
    return {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package-dir',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--report-dir',type=Path,required=True)
    args=parser.parse_args()
    root=args.package_dir.resolve(); report_dir=args.report_dir.resolve()
    if report_dir.is_relative_to(root): parser.error('report directory must be outside package')
    report_dir.mkdir(parents=True,exist_ok=True)
    report_path=report_dir/'offline-verification.json'
    if report_path.exists(): parser.error('report exists; use a new report directory')
    sys.addaudithook(deny_network)
    import verify
    before=tree_hashes(root)
    try:
        manifest_path=root/'PACKAGE-MANIFEST.json'
        manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
        inputs=manifest['offline_inputs']
        report=verify.verify(verify.safe_child(root,inputs['db']),verify.safe_child(root,inputs['raw_dir']),verify.safe_child(root,inputs['export_dir']),manifest_path)
        after=tree_hashes(root)
        if before!=after: raise ValueError('Package changed during offline verification')
        report.update(network_guard='Python audit hook denies all socket events',
                      package_unchanged=True,package_dir=str(root),
                      manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                      source_version_sha256=manifest['source_version_sha256'])
        code=0
    except Exception as exc:
        report={'result':'FAILED','error_type':type(exc).__name__,'error':str(exc),'network_used':False}
        code=1
    report['observed_utc']=datetime.now(timezone.utc).isoformat()
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True,indent=2))
    return code


if __name__=='__main__': sys.exit(main())
