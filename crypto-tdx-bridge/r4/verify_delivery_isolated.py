"""Run only delivery checks, with isolated imports and all socket access denied."""
import sys
sys.dont_write_bytecode = True
import json
import os
from pathlib import Path
import runpy
import socket
from datetime import datetime, timezone

package = Path(sys.argv[1]).resolve(strict=True)
report = Path(sys.argv[2]).resolve()
if report.exists() or report.is_relative_to(package):
    raise ValueError('Report must be a new file outside package')
if not sys.flags.isolated or not sys.flags.no_site or not sys.flags.dont_write_bytecode:
    raise RuntimeError('Use python -I -S -B for isolated delivery verification')
if os.environ.get('PYTHONPATH') or os.environ.get('PYTHONHOME'):
    raise RuntimeError('Clear PYTHONPATH and PYTHONHOME before verification')
source = package / 'source'
sys.path[:0] = [str(source / 'r4'), str(source)]
from delivery_integrity import file_inventory, verify_manifest, audit_local_imports

attempts = []


def forbid(event, arguments):
    if event.startswith('socket.') and event not in ('socket.__new__',):
        attempts.append(event)
        raise RuntimeError('Network forbidden: ' + event)


sys.addaudithook(forbid)
for name in ('create_connection', 'getaddrinfo', 'gethostbyname', 'gethostbyname_ex'):
    setattr(socket, name, lambda *a, **kw: forbid('socket.offline-denied', a))
before = file_inventory(package)
manifest_count = verify_manifest(package, before)
dependencies = audit_local_imports(source)
window_report = report.with_name(report.stem + '-windows.json')
if window_report.exists():
    raise FileExistsError(window_report)
try:
    sys.argv = [str(source / 'r4/verify_completion_windows.py'),
                str(package / 'evidence/windows'), str(window_report), str(package)]
    runpy.run_path(sys.argv[0], run_name='__main__')
    windows = json.loads(window_report.read_text(encoding='utf-8'))
    if windows['status'] != 'passed_with_scope':
        raise RuntimeError('Scoped window verification failed')
    loaded = {}
    for name in ('bridge', 'rate_control', 'display', 'settings', 'external_registry', 'delivery_integrity'):
        if name in sys.modules:
            origin = Path(sys.modules[name].__file__).resolve(strict=True)
            if not origin.is_relative_to(source):
                raise RuntimeError('External local module import: ' + str(origin))
            loaded[name] = origin.relative_to(package).as_posix()
    if 'rate_control' not in loaded:
        raise RuntimeError('rate_control import was not exercised')
    after = file_inventory(package)
    if before != after or attempts:
        raise RuntimeError('Inputs changed or network attempted')
    receipt = {'status':'passed_with_scope', 'UTC':datetime.now(timezone.utc).isoformat(),
        'package':str(package), 'working_directory':os.getcwd(), 'python_flags':'-I -S -B',
        'PYTHONPATH':os.environ.get('PYTHONPATH'), 'PYTHONHOME':os.environ.get('PYTHONHOME'),
        'network_access_blocked':True, 'network_attempts':attempts,
        'local_imports':loaded, 'dependency_audit':dependencies,
        'manifest_files_checked':manifest_count,
        'files_before':before, 'files_after':after, 'all_file_names_and_hashes_unchanged':True,
        'new_sqlite_sidecars':False, 'database_uri':'mode=ro&immutable=1',
        'scope':'delivery correction only; existing window assertions replayed from frozen inputs',
        'window_receipt':str(window_report), 'accuracy_acceptance':False,
        'midnight_weekend':'PENDING', 'overall':'PARTIAL'}
    report.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'status':receipt['status'], 'report':str(report),
                      'files_unchanged':True, 'local_imports':loaded}))
except Exception as error:
    failure = {'status':'failed', 'error':repr(error), 'network_attempts':attempts,
               'files_before':before}
    try:
        failure['files_after'] = file_inventory(package)
    except Exception as inventory_error:
        failure['inventory_error'] = repr(inventory_error)
    report.write_text(json.dumps(failure, indent=2), encoding='utf-8')
    raise
